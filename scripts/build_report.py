"""从 corpus.db 聚合分析结果，生成自包含的 report.html。

用法:
    uv run --python 3.12 scripts/build_report.py
产出:
    data/analysis/report.html   (单文件,双击即开)
"""
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

from analyze import (
    AD_RE,
    ATTRACTION_HINTS,
    EMOJI_RE,
    FOOD_HINTS,
    PLACE_BLACKLIST,
    PLACE_NAME,
    PLACE_STOPWORDS,
    URL_RE,
    ad_score,
    classify_sentiment,
    extract_names,
    extract_names_by_sentiment,
    length_stats,
    load_texts,
    neg_ratio,
    nss,
    wilson_neg_lower,
)
from common import ROOT, db

OUT_DIR = ROOT / "data" / "analysis"
TEMPLATE = ROOT / "scripts" / "report_template.html"
OUT = OUT_DIR / "report.html"

TOP_N_PLACES = 25
TOP_N_FOODS = 20
TOP_N_SPOTS = 20
HIST_BINS = [0, 5, 10, 20, 40, 80, 160, 320, 640, 1280]


def _bin_lengths(lens: list[int]) -> list[int]:
    counts = [0] * (len(HIST_BINS) - 1)
    for x in lens:
        for i in range(len(HIST_BINS) - 1):
            if HIST_BINS[i] <= x < HIST_BINS[i + 1]:
                counts[i] += 1
                break
        else:
            counts[-1] += 1
    return counts


def _hist_labels() -> list[str]:
    labels = []
    for i in range(len(HIST_BINS) - 1):
        a, b = HIST_BINS[i], HIST_BINS[i + 1]
        labels.append(f"{a}–{b}")
    return labels


def _preview(s: str, n: int = 90) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    return s[:n] + ("…" if len(s) > n else "")


def main():
    with db() as conn:
        posts, comments = load_texts(conn)

    print(f"[build] posts={len(posts)} comments={len(comments)}", file=sys.stderr)

    post_texts = [(p.get("title") or "") + "\n" + (p.get("content") or "") for p in posts]
    comment_texts = [c["content"] for c in comments]
    all_texts = post_texts + comment_texts

    places, foods, attractions = extract_names(all_texts)

    # ── 情感分类 + 按情感提取实体 ──
    print("[build] classifying sentiment...", file=sys.stderr)
    post_kw = {p["id"]: p.get("keyword") or "" for p in posts}
    texts_with_sent = []
    for p in posts:
        t = (p.get("title") or "") + "\n" + (p.get("content") or "")
        sent = classify_sentiment(t, p.get("keyword") or "")
        texts_with_sent.append((t, sent))
    for c in comments:
        # 评论继承帖子的关键词
        kw = post_kw.get(c["post_id"], "")
        sent = classify_sentiment(c["content"], kw)
        texts_with_sent.append((c["content"], sent))

    sent_counts = Counter(s for _, s in texts_with_sent)
    print(f"[build] sentiment: pos={sent_counts['pos']} neg={sent_counts['neg']} neu={sent_counts['neu']}", file=sys.stderr)

    by_sent = extract_names_by_sentiment(texts_with_sent)

    def _merge_pos_neg(total_counter, sent_dict, top_n):
        """为 top_n 个实体生成含情感指标的行列表。"""
        rows = []
        for name, total in total_counter.most_common(top_n):
            p = sent_dict["pos"].get(name, 0)
            n = sent_dict["neg"].get(name, 0)
            rows.append({
                "name": name,
                "total": total,
                "pos": p,
                "neg": n,
                "neg_ratio": round(neg_ratio(p, n), 4),
                "nss": round(nss(p, n), 4),
                "wilson_neg": round(wilson_neg_lower(p, n), 4),
            })
        return rows

    foods_sentiment = _merge_pos_neg(foods, by_sent["foods"], TOP_N_FOODS)
    attractions_sentiment = _merge_pos_neg(attractions, by_sent["attractions"], TOP_N_SPOTS)
    places_sentiment = _merge_pos_neg(places, by_sent["places"], TOP_N_PLACES)

    by_source = Counter(p["source"] for p in posts)
    by_keyword = Counter(p.get("keyword") or "其他" for p in posts)
    by_source_kw = Counter((p["source"], p.get("keyword") or "其他") for p in posts)

    len_stats = length_stats(comments)
    len_hist = {
        src: _bin_lengths([len(c["content"]) for c in comments if c["source"] == src])
        for src in ("bili", "xhs")
    }

    post_ads = []
    for p in posts:
        text = ((p.get("title") or "") + " " + (p.get("content") or "")).strip()
        score, hits = ad_score(text)
        if score >= 3:
            post_ads.append({
                "id": p["id"],
                "source": p["source"],
                "keyword": p.get("keyword") or "",
                "title": _preview(p.get("title") or "", 80),
                "ad_score": score,
                "hits": ";".join(hits),
                "likes": p.get("likes") or 0,
                "comments_count": p.get("comments_count") or 0,
            })
    post_ads.sort(key=lambda x: -x["ad_score"])

    cmt_ads = []
    for c in comments:
        score, hits = ad_score(c["content"] or "")
        if score >= 3:
            cmt_ads.append({
                "post_id": c["post_id"],
                "source": c["source"],
                "preview": _preview(c["content"], 110),
                "ad_score": score,
                "hits": ";".join(hits),
                "likes": c.get("likes") or 0,
            })
    cmt_ads.sort(key=lambda x: -x["ad_score"])

    posts_table = []
    for p in posts:
        text = ((p.get("title") or "") + " " + (p.get("content") or "")).strip()
        score, _ = ad_score(text)
        posts_table.append({
            "id": p["id"],
            "source": p["source"],
            "keyword": p.get("keyword") or "",
            "title": _preview(p.get("title") or "(无标题)", 70),
            "likes": p.get("likes") or 0,
            "comments": p.get("comments_count") or 0,
            "ad_score": score,
            "url": p.get("url") or "",
        })
    posts_table.sort(key=lambda x: (-x["comments"], -x["likes"]))

    co_occur = Counter()
    hint_re = re.compile(
        "(" + FOOD_HINTS.pattern + "|" + ATTRACTION_HINTS.pattern + ")"
    )
    for t in all_texts:
        if not t:
            continue
        hits = set(FOOD_HINTS.findall(t)) | set(ATTRACTION_HINTS.findall(t))
        hits = sorted(hits)
        for i in range(len(hits)):
            for j in range(i + 1, len(hits)):
                co_occur[(hits[i], hits[j])] += 1

    top_co = [
        {"source": a, "target": b, "value": v}
        for (a, b), v in co_occur.most_common(30)
        if v >= 2
    ]

    meta = {
        "generated_at": _now(),
        "posts_total": len(posts),
        "comments_total": len(comments),
        "keywords_total": len(by_keyword),
        "flagged_posts": len(post_ads),
        "flagged_comments": len(cmt_ads),
        "sentiment_pos": sent_counts["pos"],
        "sentiment_neg": sent_counts["neg"],
        "sentiment_neu": sent_counts["neu"],
    }

    data = {
        "meta": meta,
        "sources": [
            {"source": s, "count": n} for s, n in by_source.most_common()
        ],
        "keywords": [
            {"keyword": k, "count": n} for k, n in by_keyword.most_common()
        ],
        "source_keyword": [
            {"source": s, "keyword": k, "count": n}
            for (s, k), n in by_source_kw.most_common()
        ],
        "foods": [
            {"name": n, "count": c} for n, c in foods.most_common(TOP_N_FOODS)
        ],
        "attractions": [
            {"name": n, "count": c} for n, c in attractions.most_common(TOP_N_SPOTS)
        ],
        "places": [
            {"name": n, "count": c} for n, c in places.most_common(TOP_N_PLACES)
        ],
        "foods_sentiment": foods_sentiment,
        "attractions_sentiment": attractions_sentiment,
        "places_sentiment": places_sentiment,
        "length_stats": len_stats,
        "length_hist": {
            "labels": _hist_labels(),
            "bili": len_hist["bili"],
            "xhs": len_hist["xhs"],
        },
        "ad_posts": post_ads[:60],
        "ad_comments": cmt_ads[:80],
        "posts_table": posts_table[:200],
        "cooccur": top_co,
    }

    tpl = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    rendered = tpl.replace("/*__DATA_JSON__*/{}", payload)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(rendered, encoding="utf-8")
    print(f"[out] {OUT}  ({len(rendered)/1024:.1f} KB)", file=sys.stderr)


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M")


if __name__ == "__main__":
    main()
