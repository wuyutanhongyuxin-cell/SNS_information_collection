"""Bili 批量采集：按关键词列表依次调用 fetch_bili.py，统计去重产出。"""
import subprocess
import sys
import sqlite3
import time
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import db

PYTHON = r"E:\python\python_3.13\python.exe"
FETCH_SCRIPT = str(Path(__file__).resolve().parent / "fetch_bili.py")

KEYWORDS = [
    # ---- 已有关键词，加大 limit 补满 ----
    ("西安 美食", 50),
    ("西安 避雷", 50),
    ("西安 行程", 50),
    ("西安 住宿", 50),
    ("西安 攻略", 50),
    ("西安 美食 踩雷", 50),
    # ---- 美食细分 ----
    ("西安 回民街 美食", 50),
    ("西安 烤肉 推荐", 50),
    ("西安 泡馍", 50),
    ("西安 肉夹馍", 40),
    ("西安 凉皮", 40),
    ("西安 夜市 小吃", 50),
    ("西安 洒金桥 美食", 40),
    # ---- 景点/出行 ----
    ("西安 大唐不夜城", 50),
    ("西安 兵马俑 攻略", 40),
    ("西安 城墙", 40),
    ("西安 华清宫 长恨歌", 30),
    # ---- 旅行规划 ----
    ("五一 西安 旅游", 50),
    ("西安 三日游", 50),
    ("西安 自由行 攻略", 40),
]


def count_bili():
    with db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as posts, "
            "(SELECT COUNT(*) FROM comments c JOIN posts p ON p.id=c.post_id WHERE p.source='bili') as cmts "
            "FROM posts WHERE source='bili'"
        ).fetchone()
        return row["posts"], row["cmts"]


def main():
    before_posts, before_cmts = count_bili()
    print(f"[batch] 开始前: {before_posts} posts, {before_cmts} comments", file=sys.stderr)

    for i, (kw, limit) in enumerate(KEYWORDS, 1):
        print(f"\n[batch] === [{i}/{len(KEYWORDS)}] keyword={kw!r} limit={limit} ===", file=sys.stderr)
        try:
            p = subprocess.run(
                [PYTHON, FETCH_SCRIPT, "--keyword", kw, "--limit", str(limit)],
                timeout=600,
                cwd=str(Path(FETCH_SCRIPT).parent),
            )
            if p.returncode != 0:
                print(f"[batch] WARNING: {kw} exited with code {p.returncode}", file=sys.stderr)
        except subprocess.TimeoutExpired:
            print(f"[batch] TIMEOUT: {kw}", file=sys.stderr)
        except Exception as e:
            print(f"[batch] ERROR: {kw}: {e}", file=sys.stderr)

        cur_posts, cur_cmts = count_bili()
        print(f"[batch] 当前累计: {cur_posts} posts (+{cur_posts - before_posts}), "
              f"{cur_cmts} comments (+{cur_cmts - before_cmts})", file=sys.stderr)

        if i < len(KEYWORDS):
            pause = random.uniform(3.0, 8.0)
            print(f"[batch] 关键词间隔 {pause:.1f}s", file=sys.stderr)
            time.sleep(pause)

    after_posts, after_cmts = count_bili()
    print(f"\n[batch] === 完成 ===", file=sys.stderr)
    print(f"[batch] 之前: {before_posts} posts, {before_cmts} comments", file=sys.stderr)
    print(f"[batch] 之后: {after_posts} posts, {after_cmts} comments", file=sys.stderr)
    print(f"[batch] 新增: +{after_posts - before_posts} posts, +{after_cmts - before_cmts} comments", file=sys.stderr)


if __name__ == "__main__":
    main()
