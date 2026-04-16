import hashlib
import json
import os
import random
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "corpus.db"
RAW_DIR = ROOT / "raw"
LOG_DIR = ROOT / "logs"

SALT = os.environ.get("AUTHOR_HASH_SALT", "xian-corpus-default-salt-change-me")


def ensure_dirs():
    (ROOT / "data").mkdir(exist_ok=True)
    (RAW_DIR / "bili").mkdir(parents=True, exist_ok=True)
    (RAW_DIR / "xhs").mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)


def db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass
    return conn


def author_hash(name_or_id: str) -> str:
    if not name_or_id:
        return ""
    h = hashlib.sha256((SALT + str(name_or_id)).encode("utf-8")).hexdigest()
    return h[:16]


def jitter(lo=2.0, hi=5.0):
    t = random.gauss((lo + hi) / 2, (hi - lo) / 4)
    t = max(lo, min(hi, t))
    time.sleep(t)


def long_pause_chance(p=0.05, lo=10, hi=30):
    if random.random() < p:
        t = random.uniform(lo, hi)
        print(f"[pause] long stop {t:.1f}s", file=sys.stderr)
        time.sleep(t)


def save_raw(source: str, name: str, data):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    p = RAW_DIR / source / f"{ts}_{name}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def log_fetch(source: str, keyword: str, posts: int, comments: int, note: str = ""):
    LOG_DIR.mkdir(exist_ok=True)
    line = f"{datetime.now().isoformat()}\t{source}\t{keyword}\tposts={posts}\tcomments={comments}\t{note}\n"
    (LOG_DIR / "fetch.log").open("a", encoding="utf-8").write(line)


def today_count(source: str) -> int:
    """返回今天已抓取的帖子数（用于限流）。"""
    log_file = LOG_DIR / "fetch.log"
    if not log_file.exists():
        return 0
    today = datetime.now().date().isoformat()
    total = 0
    with log_file.open(encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) < 4:
                continue
            if parts[0].startswith(today) and parts[1] == source:
                kv = dict(p.split("=", 1) for p in parts[3:5] if "=" in p)
                total += int(kv.get("posts", 0))
    return total
