"""B 站匿名抓取：关键词 → 视频列表 → 每视频详情+评论 → 入库。"""
import argparse
import json
import os
import random
import subprocess
import sys
import time

import requests

from common import (
    author_hash,
    db,
    ensure_dirs,
    jitter,
    log_fetch,
    long_pause_chance,
    save_raw,
)

BILI_CMD = "bili"
API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com",
    "Accept": "application/json",
}


def run_bili(args: list[str]) -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run(
        [BILI_CMD, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=90,
    )
    if p.returncode != 0:
        raise RuntimeError(f"bili {args} failed: {p.stderr[:500]}")
    return json.loads(p.stdout)


def search_videos(keyword: str, max_n: int) -> list[dict]:
    res = run_bili(["search", keyword, "--type", "video", "--max", str(max_n), "--json"])
    if not res.get("ok"):
        raise RuntimeError(f"search failed: {res}")
    return res.get("data", [])


def fetch_video_detail(bvid: str) -> dict:
    """用 CLI 拿视频基本信息（不含评论）。"""
    res = run_bili(["video", bvid, "--json"])
    if not res.get("ok"):
        raise RuntimeError(f"video {bvid} failed: {res}")
    return res["data"]


def fetch_comments_direct(aid: int, bvid: str, max_pages: int = 3) -> list[dict]:
    """用 /x/v2/reply/main 游标分页拉评论，绕过 CLI 的 3 条限制。"""
    all_replies = []
    seen = set()
    next_page = 0
    offset = ""

    for _ in range(max_pages):
        params = {"oid": aid, "type": 1, "mode": 3, "ps": 20, "next": next_page}
        if offset:
            params["pagination_str"] = json.dumps({"offset": offset})

        r = requests.get(
            "https://api.bilibili.com/x/v2/reply/main",
            params=params,
            headers={**API_HEADERS, "Referer": f"https://www.bilibili.com/video/{bvid}/"},
            timeout=15,
        )
        r.raise_for_status()
        resp = r.json()
        if resp.get("code") != 0:
            break

        data = resp.get("data") or {}
        replies = data.get("replies") or []
        if not replies:
            break

        for rp in replies:
            rpid = rp.get("rpid")
            if rpid and rpid not in seen:
                seen.add(rpid)
                all_replies.append({
                    "id": str(rpid),
                    "message": (rp.get("content") or {}).get("message", ""),
                    "like": rp.get("like", 0),
                    "author": {"id": (rp.get("member") or {}).get("mid", "")},
                })

        cursor = data.get("cursor") or {}
        if cursor.get("is_end"):
            break
        next_page = cursor.get("next", next_page + 1)
        pag = (cursor.get("pagination_reply") or {}).get("next_offset", "")
        offset = pag if pag else ""

        time.sleep(random.uniform(0.3, 0.8))

    return all_replies


def get_aid(bvid: str) -> int:
    r = requests.get(
        "https://api.bilibili.com/x/web-interface/view",
        params={"bvid": bvid},
        headers=API_HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        raise RuntimeError(f"get aid for {bvid}: {d.get('message')}")
    return d["data"]["aid"]


def upsert_post(conn, source_id: str, title: str, author_id: str,
                description: str, stats: dict, url: str, keyword: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO posts (source, source_id, post_type, title, author_hash,
                           content, likes, comments_count, url, keyword)
        VALUES ('bili', ?, 'video', ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, source_id) DO UPDATE SET
            title = excluded.title,
            content = excluded.content,
            likes = excluded.likes,
            comments_count = excluded.comments_count
        RETURNING id
        """,
        (
            source_id,
            title,
            author_hash(author_id),
            description,
            stats.get("like"),
            stats.get("danmaku"),
            url,
            keyword,
        ),
    )
    return cur.fetchone()["id"]


def insert_comments(conn, post_id: int, comments: list[dict]):
    rows = [
        (
            post_id,
            c.get("id"),
            author_hash((c.get("author") or {}).get("id", "")),
            c.get("message"),
            c.get("like"),
        )
        for c in comments
    ]
    conn.executemany(
        """
        INSERT INTO comments (post_id, source_id, author_hash, content, likes)
        VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    ensure_dirs()
    print(f"[bili] keyword={args.keyword!r} limit={args.limit}", file=sys.stderr)

    videos = search_videos(args.keyword, args.limit)
    save_raw("bili", f"search_{args.keyword}", videos)
    print(f"[bili] search returned {len(videos)} videos", file=sys.stderr)

    posts_ok = 0
    comments_ok = 0
    with db() as conn:
        for i, v in enumerate(videos, 1):
            bvid = v.get("bvid") or v.get("id")
            if not bvid:
                continue
            existing = conn.execute(
                "SELECT id FROM posts WHERE source='bili' AND source_id=?", (bvid,)
            ).fetchone()
            if existing:
                print(f"[bili] {i}/{len(videos)} {bvid} already in DB, skip", file=sys.stderr)
                continue
            try:
                detail = fetch_video_detail(bvid)
                video = detail.get("video", {})
                owner = video.get("owner", {})
                stats = video.get("stats", {})

                aid = get_aid(bvid)
                comments = fetch_comments_direct(aid, bvid, max_pages=3)

                post_id = upsert_post(
                    conn,
                    source_id=video.get("bvid", bvid),
                    title=video.get("title", ""),
                    author_id=owner.get("id", ""),
                    description=video.get("description", ""),
                    stats=stats,
                    url=video.get("url", ""),
                    keyword=args.keyword,
                )
                insert_comments(conn, post_id, comments)
                posts_ok += 1
                comments_ok += len(comments)
                conn.commit()

                save_raw("bili", f"video_{bvid}", {**detail, "comments_direct": comments})
                print(f"[bili] {i}/{len(videos)} {bvid} + {len(comments)} comments", file=sys.stderr)

                jitter(1.0, 3.0)
                long_pause_chance(p=0.1, lo=5, hi=15)
            except Exception as e:
                print(f"[bili] skip {bvid}: {e}", file=sys.stderr)
                try:
                    conn.rollback()
                except Exception:
                    pass
                jitter(2.0, 5.0)

    log_fetch("bili", args.keyword, posts_ok, comments_ok)
    print(f"[bili] done: posts={posts_ok} comments={comments_ok}", file=sys.stderr)


if __name__ == "__main__":
    main()
