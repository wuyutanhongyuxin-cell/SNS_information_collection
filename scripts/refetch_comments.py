"""补抓 Bili 视频评论：用 /x/v2/reply/main 接口（游标分页），绕过 CLI 3 条限制。

对 DB 中所有 bili 帖子，拉取评论（每页 20，最多 max_pages 页），去重后入库。
"""
import argparse
import json
import random
import sys
import time

import requests

from common import db, ensure_dirs, save_raw, author_hash, log_fetch

API_URL = "https://api.bilibili.com/x/v2/reply/main"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Origin": "https://www.bilibili.com",
    "Accept": "application/json",
}


def get_aid_from_bvid(bvid: str) -> int:
    r = requests.get(
        "https://api.bilibili.com/x/web-interface/view",
        params={"bvid": bvid},
        headers=HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"get aid failed for {bvid}: {data.get('message')}")
    return data["data"]["aid"]


def fetch_all_comments(aid: int, bvid: str, max_pages: int = 5) -> list[dict]:
    """用 /reply/main 游标分页拉评论。"""
    all_replies = []
    seen = set()
    next_page = 0
    offset = ""

    for _ in range(max_pages):
        params = {"oid": aid, "type": 1, "mode": 3, "ps": 20, "next": next_page}
        if offset:
            params["pagination_str"] = json.dumps({"offset": offset})

        r = requests.get(
            API_URL,
            params=params,
            headers={**HEADERS, "Referer": f"https://www.bilibili.com/video/{bvid}/"},
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
                all_replies.append(rp)

        cursor = data.get("cursor") or {}
        if cursor.get("is_end"):
            break
        next_page = cursor.get("next", next_page + 1)
        pag = (cursor.get("pagination_reply") or {}).get("next_offset", "")
        offset = pag if pag else ""

        time.sleep(random.uniform(0.3, 0.8))

    return all_replies


def parse_reply(r: dict) -> dict:
    member = r.get("member", {})
    return {
        "source_id": str(r.get("rpid", "")),
        "author_hash": author_hash(member.get("mid", "")),
        "content": (r.get("content") or {}).get("message", ""),
        "likes": r.get("like", 0),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-pages", type=int, default=5, help="每个视频最多拉几页评论（每页20条）")
    parser.add_argument("--dry-run", action="store_true", help="只统计不入库")
    args = parser.parse_args()

    ensure_dirs()
    with db() as conn:
        posts = conn.execute(
            "SELECT id, source_id, title FROM posts WHERE source='bili'"
        ).fetchall()

    print(f"[refetch] 共 {len(posts)} 个 bili 视频待补抓评论", file=sys.stderr)

    total_new = 0
    for i, post in enumerate(posts, 1):
        post_id = post["id"]
        bvid = post["source_id"]
        title = (post["title"] or "")[:30]
        try:
            aid = get_aid_from_bvid(bvid)
            replies = fetch_all_comments(aid, bvid, max_pages=args.max_pages)
            parsed = [parse_reply(r) for r in replies]
            parsed = [p for p in parsed if p["content"]]

            if args.dry_run:
                print(f"[refetch] {i}/{len(posts)} {bvid} -> {len(parsed)} comments  {title}", file=sys.stderr)
                total_new += len(parsed)
                time.sleep(random.uniform(0.3, 0.8))
                continue

            with db() as conn:
                existing = set(
                    r["source_id"] for r in conn.execute(
                        "SELECT source_id FROM comments WHERE post_id=?", (post_id,)
                    ).fetchall()
                    if r["source_id"]
                )
                new_comments = [p for p in parsed if p["source_id"] not in existing]
                if new_comments:
                    conn.executemany(
                        "INSERT INTO comments (post_id, source_id, author_hash, content, likes) VALUES (?, ?, ?, ?, ?)",
                        [(post_id, c["source_id"], c["author_hash"], c["content"], c["likes"]) for c in new_comments],
                    )
                    conn.commit()
                print(f"[refetch] {i}/{len(posts)} {bvid} +{len(new_comments)} new (total {len(parsed)})  {title}", file=sys.stderr)
                total_new += len(new_comments)

            save_raw("bili", f"comments_{bvid}", [parse_reply(r) for r in replies])
            time.sleep(random.uniform(1.0, 2.5))

        except Exception as e:
            print(f"[refetch] {i}/{len(posts)} {bvid} ERROR: {e}", file=sys.stderr)
            time.sleep(random.uniform(2.0, 4.0))

    log_fetch("bili", "refetch_comments", 0, total_new, "backfill")
    print(f"\n[refetch] 完成！新增 {total_new} 条评论", file=sys.stderr)


if __name__ == "__main__":
    main()
