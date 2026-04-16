from common import db, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    post_type       TEXT,
    title           TEXT,
    author_hash     TEXT,
    content         TEXT,
    likes           INTEGER,
    comments_count  INTEGER,
    published_at    TEXT,
    fetched_at      TEXT DEFAULT CURRENT_TIMESTAMP,
    url             TEXT,
    keyword         TEXT,
    UNIQUE(source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_posts_source       ON posts(source);
CREATE INDEX IF NOT EXISTS idx_posts_keyword      ON posts(keyword);
CREATE INDEX IF NOT EXISTS idx_posts_published    ON posts(published_at);

CREATE TABLE IF NOT EXISTS comments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id         INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    source_id       TEXT,
    author_hash     TEXT,
    content         TEXT,
    likes           INTEGER,
    published_at    TEXT,
    fetched_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);

CREATE TABLE IF NOT EXISTS danmaku (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id         INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    content         TEXT,
    send_time       REAL,
    mode            INTEGER,
    fetched_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_danmaku_post ON danmaku(post_id);
"""


def main():
    ensure_dirs()
    with db() as conn:
        conn.executescript(SCHEMA)
    print("DB initialized at", "data/corpus.db")


if __name__ == "__main__":
    main()
