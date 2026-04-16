"""小红书登录抓取：搜索 → 读正文 → 读评论（全分页）→ 入库。

硬限流：每天 ≤ DAILY_CAP 条帖子。cookie 从浏览器自动读取。
"""
import argparse
import json
import os
import subprocess
import sys

from common import (
    author_hash,
    db,
    ensure_dirs,
    jitter,
    log_fetch,
    long_pause_chance,
    save_raw,
    today_count,
)

XHS_CMD = "xhs"
DAILY_CAP = 150


def run_xhs(args: list[str]) -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run(
        [XHS_CMD, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
    )
    if p.returncode != 0:
        raise RuntimeError(f"xhs {args} failed: {p.stderr[:500]}")
    out = p.stdout.strip()
    if not out:
        return {}
    return json.loads(out)


def search_notes(keyword: str, page: int = 1) -> list[dict]:
    res = run_xhs(["search", keyword, "--page", str(page), "--json"])
    if not res.get("ok"):
        raise RuntimeError(f"search failed: {res}")
    data = res.get("data", [])
    return data if isinstance(data, list) else data.get("notes", data.get("items", []))


def read_note(note_id: str, xsec_token: str | None) -> dict:
    args = ["read", note_id, "--json"]
    if xsec_token:
        args += ["--xsec-token", xsec_token]
    res = run_xhs(args)
    if not res.get("ok"):
        raise RuntimeError(f"read failed: {res}")
    return res.get("data", {})


def read_comments(note_id: str, xsec_token: str | None) -> list[dict]:
    args = ["comments", note_id, "--all", "--json"]
    if xsec_token:
        args += ["--xsec-token", xsec_token]
    res = run_xhs(args)
    if not res.get("ok"):
        print(f"[xhs] comments error {note_id}: {res.get('error')}", file=sys.stderr)
        return []
    data = res.get("data", [])
    return data if isinstance(data, list) else data.get("comments", data.get("items", []))


def upsert_post(conn, note: dict, content: str, keyword: str) -> int:
    # 搜索结果结构：{id, xsec_token, note_card:{user, interact_info, type, display_title}}
    # read 详情结构（扁平）会在 merged 里覆盖
    nc = note.get("note_card", {}) or {}
    source_id = note.get("id") or note.get("note_id") or ""
    author = nc.get("user") or note.get("user") or note.get("author") or {}
    author_id = author.get("user_id") or author.get("id") or author.get("userId") or ""
    title = nc.get("display_title") or note.get("title") or note.get("display_title") or ""
    interact = nc.get("interact_info") or note.get("interact_info") or {}
    likes = interact.get("liked_count") or note.get("liked_count") or note.get("likes")
    comments_count = interact.get("comment_count") or note.get("comment_count") or note.get("comments_count")
    url = note.get("url") or f"https://www.xiaohongshu.com/explore/{source_id}"
    note_type = nc.get("type") or note.get("type") or note.get("note_type") or "note"

    cur = conn.execute(
        """
        INSERT INTO posts (source, source_id, post_type, title, author_hash,
                           content, likes, comments_count, url, keyword)
        VALUES ('xhs', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, source_id) DO UPDATE SET
            title = excluded.title,
            content = excluded.content,
            likes = excluded.likes,
            comments_count = excluded.comments_count
        RETURNING id
        """,
        (source_id, note_type, title, author_hash(author_id), content,
         likes, comments_count, url, keyword),
    )
    return cur.fetchone()["id"]


def insert_comments(conn, post_id: int, comments: list[dict]):
    rows = []
    for c in comments:
        cid = c.get("id") or c.get("comment_id")
        author = c.get("user") or c.get("author") or {}
        aid = author.get("id") or author.get("user_id") or ""
        rows.append((
            post_id,
            cid,
            author_hash(aid),
            c.get("content") or c.get("text") or "",
            c.get("likes") or c.get("like_count") or 0,
        ))
    conn.executemany(
        "INSERT INTO comments (post_id, source_id, author_hash, content, likes) VALUES (?, ?, ?, ?, ?)",
        rows,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--skip-comments", action="store_true")
    args = parser.parse_args()

    done_today = today_count("xhs")
    if done_today >= DAILY_CAP:
        print(f"[xhs] daily cap reached ({done_today}/{DAILY_CAP}), aborting", file=sys.stderr)
        sys.exit(2)
    remain = DAILY_CAP - done_today
    target = min(args.limit, remain)
    print(f"[xhs] today already {done_today}, allow {remain}, will fetch {target}", file=sys.stderr)

    ensure_dirs()
    notes = search_notes(args.keyword)
    save_raw("xhs", f"search_{args.keyword}", notes)
    notes = notes[:target]
    print(f"[xhs] will process {len(notes)} notes", file=sys.stderr)

    posts_ok = 0
    comments_ok = 0
    with db() as conn:
        for i, n in enumerate(notes, 1):
            nid = n.get("id") or n.get("note_id")
            token = n.get("xsec_token") or n.get("xsecToken")
            if not nid:
                continue
            try:
                detail = read_note(nid, token)
                content = detail.get("desc") or detail.get("content") or ""
                merged = {**n, **detail}
                post_id = upsert_post(conn, merged, content, args.keyword)
                save_raw("xhs", f"note_{nid}", detail)
                jitter(3.0, 8.0)

                cmts = []
                if not args.skip_comments:
                    cmts = read_comments(nid, token)
                    insert_comments(conn, post_id, cmts)
                    save_raw("xhs", f"comments_{nid}", cmts)

                posts_ok += 1
                comments_ok += len(cmts)
                conn.commit()
                print(f"[xhs] {i}/{len(notes)} {nid} + {len(cmts)} comments", file=sys.stderr)

                jitter(3.0, 8.0)
                if i % 20 == 0:
                    long_pause_chance(p=1.0, lo=10, hi=30)
                else:
                    long_pause_chance(p=0.05, lo=10, hi=30)
            except Exception as e:
                print(f"[xhs] skip {nid}: {e}", file=sys.stderr)
                jitter(5.0, 10.0)

    log_fetch("xhs", args.keyword, posts_ok, comments_ok)
    print(f"[xhs] done: posts={posts_ok} comments={comments_ok}", file=sys.stderr)


if __name__ == "__main__":
    main()
