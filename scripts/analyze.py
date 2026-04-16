"""语料分析：高频店名（jieba NER）、美食/景点、评论分布、疑似广告、情感分类。

输入：data/corpus.db
输出：stdout 汇总 + data/analysis/*.csv
"""
import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path
from statistics import median

import jieba
import jieba.posseg as pseg

from common import ROOT, db

# --------------- 知网 HowNet 情感词典 ---------------
LEXICON_DIR = ROOT / "data" / "lexicons"


def _load_lexicon(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


POS_WORDS = _load_lexicon(LEXICON_DIR / "pos_emotion.txt") | _load_lexicon(LEXICON_DIR / "pos_eval.txt")
NEG_WORDS = _load_lexicon(LEXICON_DIR / "neg_emotion.txt") | _load_lexicon(LEXICON_DIR / "neg_eval.txt")
NEGATION_WORDS = _load_lexicon(LEXICON_DIR / "negation.txt")

# 美食/旅游领域补充词（词典未覆盖的）
POS_WORDS |= {
    "好吃", "推荐", "必吃", "强推", "超好吃", "太好吃", "真香", "太香了",
    "正宗", "地道", "实惠", "划算", "性价比高", "排队也值", "必去",
    "惊艳", "回味", "满足", "好喝", "超赞", "封神",
}
NEG_WORDS |= {
    "避雷", "踩雷", "难吃", "不好吃", "踩坑", "翻车", "智商税", "宰客",
    "拉肚子", "不新鲜", "不干净", "服务差", "态度差", "名不副实",
    "商业化严重", "过于商业化", "难喝", "不会再去", "后悔",
}

# 关键词本身暗示负面
NEG_QUERY_HINTS = {"避雷", "踩雷", "排雷"}


def classify_sentiment(text: str, keyword: str = "") -> str:
    """基于知网词典 + jieba 分词判断情感：'pos' / 'neg' / 'neu'。

    算法：jieba 分词后逐词匹配正/负面词典，遇到否定词翻转下一个情感词极性。
    """
    if not text:
        return "neu"
    words = [w for w in jieba.cut(text) if w.strip()]
    pos_score = 0
    neg_score = 0
    negate = False
    for w in words:
        if w in NEGATION_WORDS:
            negate = True
            continue
        if w in POS_WORDS:
            if negate:
                neg_score += 1
            else:
                pos_score += 1
            negate = False
        elif w in NEG_WORDS:
            if negate:
                pos_score += 1
            else:
                neg_score += 1
            negate = False
        else:
            negate = False  # 否定词作用范围仅限紧邻的情感词

    # 搜索关键词含避雷/踩雷给负面加权
    if keyword:
        for hint in NEG_QUERY_HINTS:
            if hint in keyword:
                neg_score += 2
                break

    if neg_score > pos_score:
        return "neg"
    if pos_score > neg_score:
        return "pos"
    return "neu"

OUT_DIR = ROOT / "data" / "analysis"

# --------------- 自定义西安餐饮词典 ---------------
XIAN_SHOP_DICT = [
    # 肉夹馍
    "子午路张记", "子午路张记肉夹馍", "樊记", "樊记肉夹馍", "秦豫肉夹馍",
    "刘峰肉夹馍", "肉夹馍张记",
    # 凉皮/米皮
    "魏家凉皮", "薛昌利", "薛昌利米皮", "吴鑫",
    # 小炒
    "刘信", "刘信小炒", "马洪小炒", "天锡家小炒",
    # 泡馍
    "老孙家", "老孙家泡馍", "同盛祥", "老白家", "老白家泡馍", "水围城",
    # 灌汤包/蒸饺
    "贾三灌汤包", "贾三", "志亮灌汤蒸饺", "志亮蒸饺", "志亮",
    # 综合/陕菜
    "醉长安", "长安大排档", "陕焰", "袁家村", "陕拾叁",
    "福满长安", "福满长安陕菜", "三根电杆陕菜馆", "坊上庭院",
    "高家大院",
    # 特色小吃
    "花奶奶酸梅汤", "盛志望麻酱酿皮", "小贾八宝粥",
    "东南亚甑糕", "红红酸菜炒米", "定家小酥肉",
    "刘纪孝", "老铁家胡辣汤",
    # 面馆
    "汉城路刀削面", "魏斯理", "马虎面馆", "芳玲面屋", "爱骅裤带面馆",
    # 烤肉
    "刚刚烤肉", "清真刚刚烤肉", "尹珍珠烤肉", "三宝烤肉", "叁宝烤肉",
    "四宝烤肉", "哈力家烤肉", "郭楠烤肉", "马蜂烤肉", "勇利烤肉",
    "马波烤肉", "买买提烤肉", "烧烤小杨烤肉", "火炉旁烤肉",
    "唐间烤肉", "马乐烤肉", "哈里家", "坊上烤肉",
    # 水盆
    "芳芳水盆", "芳芳水盆羊杂", "盈盈水盆",
    # 其他
    "海荣锅贴", "春发生", "春发生葫芦头",
    "苗记", "李记", "赵记", "罗记", "吴记", "张记", "郑记",
    "德发兴", "汉巴味德", "马二饺子馆", "马二酸汤",
    "赛格七楼", "夜村米酒屋", "林间山庄",
    "老刘家", "李家搅团",
    # 街巷（美食聚集地）
    "大皮院", "小皮院", "西羊市", "北广济街", "教场门", "洒金桥",
]

for word in XIAN_SHOP_DICT:
    jieba.add_word(word, freq=50000, tag="nz")

# --------------- 后缀正则（兜底，只用餐饮专用后缀） ---------------
PLACE_SUFFIX = r"(?:记|坊|斋|轩|苑|堂|铺|屋|庄|面馆|饺子馆|陕菜馆|烤肉|大排档)"
PLACE_NAME = re.compile(rf"([\u4e00-\u9fa5]{{1,6}}{PLACE_SUFFIX})")
PLACE_BLACKLIST = re.compile(
    r"^(这|那|一|几|每|多|别|小|大|老|新|本|连锁|家|自家|整|全|某|哪|其实|周围|好多|千万)"
)
PLACE_STOPWORDS = {
    "游记", "笔记", "行程记", "日记", "传记", "过来记", "过家记",
    "旅行游记", "阿布游记", "冬冬游记", "冬冬游玩笔记",
    "延安行程记", "文博记", "咋约文博记", "东郊记",
    "闭馆", "周一闭馆", "主馆", "进馆", "烤肉", "请记", "美食记",
    "街坊", "周围街坊", "叫回坊", "其实坊", "去坊", "上坊",
    "店铺", "满屋", "天堂", "食堂", "礼堂", "教堂",
    "本地堂", "附近本地堂",
}

FOOD_HINTS = re.compile(
    r"(肉夹馍|凉皮|臊子面|油泼面|biangbiang面|biangbiang|葫芦鸡|泡馍|羊肉泡馍|牛肉泡馍|"
    r"甑糕|柿子饼|镜糕|灌汤包|biang|胡辣汤|肉丸胡辣汤|米皮|擀面皮|"
    r"水盆羊肉|葫芦头|酸汤水饺|臊子|裤带面|蘸水面|搅团|锅盔|"
    r"粉汤羊血|烤肉|腊牛肉|酿皮|麻酱凉皮|八宝粥|酸梅汤|"
    r"蒸饺|小炒|小炒泡馍|大刀面|手擀面|刀削面|岐山臊子面|"
    r"羊杂汤|水盆|涮牛肚|烤馍|炒凉粉|饸络|滋卷)", re.IGNORECASE
)

ATTRACTION_HINTS = re.compile(
    r"(钟楼|鼓楼|回民街|大唐不夜城|大雁塔|小雁塔|城墙|永兴坊|兵马俑|华清宫|华清池|"
    r"华山|碑林|碑林博物馆|大明宫|曲江|芙蓉园|大唐芙蓉园|西安博物院|"
    r"陕西历史博物馆|陕博|易俗社|洒金桥|长恨歌|大唐西市|"
    r"书院门|南门|永宁门|含光门|朱雀门|北院门|德福巷|"
    r"秦始皇陵|兵马俑博物馆|半坡|白鹿原|白鹿仓|昆明池|"
    r"大皮院|小皮院|西羊市|北广济街)"
)

# --------------- 上下文提取模式 ---------------
CONTEXT_PATTERNS = [
    re.compile(r"(?:去了?|推荐|吃了?|试试|打卡了?)(?:一下)?[「「【\"]?([\u4e00-\u9fa5]{2,8}(?:路|街)?[\u4e00-\u9fa5]{1,6})[」」】\"]?(?:的|家|，|,|。|！|\s|很|真|超|特|也|还|就|都)"),
    re.compile(r"[「「【\"]([\u4e00-\u9fa5]{2,12})[」」】\"](?:好吃|不错|推荐|值得|踩雷|一般|难吃)"),
]

AD_KEYWORDS = [
    "必打卡", "绝绝子", "yyds", "宝子", "姐妹们冲", "姐妹们必", "合作", "广告",
    "赞助", "探店", "福利", "团购", "私信", "v我", "加v", "vx", "微信",
    "代运营", "排雷老字号", "全网最", "吊打", "天花板",
]
AD_RE = re.compile("|".join(re.escape(k) for k in AD_KEYWORDS), re.IGNORECASE)
URL_RE = re.compile(r"https?://|www\.")
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF]")


def load_texts(conn):
    posts = [dict(r) for r in conn.execute(
        "SELECT id, source, title, content, likes, comments_count, keyword FROM posts"
    ).fetchall()]
    comments = [dict(r) for r in conn.execute(
        "SELECT c.id, c.post_id, c.content, c.likes, p.source "
        "FROM comments c JOIN posts p ON p.id=c.post_id "
        "WHERE c.content IS NOT NULL AND length(c.content) > 0"
    ).fetchall()]
    return posts, comments


SHOP_DICT_SET = set(XIAN_SHOP_DICT)

ATTRACTION_SET = set()
for alt in ATTRACTION_HINTS.pattern.strip("()").split("|"):
    ATTRACTION_SET.add(alt.replace("\\", ""))

FOOD_SET = set()
for alt in FOOD_HINTS.pattern.strip("()").split("|"):
    FOOD_SET.add(alt.replace("\\", ""))

def _is_valid_shop_suffix(name: str) -> bool:
    if name in PLACE_STOPWORDS or PLACE_BLACKLIST.match(name):
        return False
    if name in ATTRACTION_SET or name in FOOD_SET:
        return False
    if len(name) < 2 or len(name) > 8:
        return False
    if re.search(r"[的了在去来回就也还都是有没不我你他她它们吃逛看和或者]", name):
        return False
    if re.match(r"^\d", name):
        return False
    if re.search(r"(食堂|教堂|礼堂|课堂)$", name):
        return False
    return True


def extract_names(texts: list[str]) -> tuple[Counter, Counter, Counter]:
    places, foods, attractions = Counter(), Counter(), Counter()
    for t in texts:
        if not t:
            continue
        for m in FOOD_HINTS.findall(t):
            foods[m] += 1
        for m in ATTRACTION_HINTS.findall(t):
            attractions[m] += 1

        # jieba 分词：只匹配自定义词典中的已知店名
        for word, _flag in pseg.cut(t):
            word = word.strip()
            if word in SHOP_DICT_SET:
                places[word] += 1

        # 后缀正则兜底（XX记/馆/坊/楼/店 等短名）
        for m in PLACE_NAME.findall(t):
            name = m.strip()
            if name in SHOP_DICT_SET:
                continue  # 已在 jieba 阶段计数
            if _is_valid_shop_suffix(name):
                places[name] += 1

    return places, foods, attractions


def extract_names_by_sentiment(
    texts_with_sentiment: list[tuple[str, str]],
) -> dict:
    """按情感极性分别统计实体频次。

    参数: [(text, sentiment), ...] 其中 sentiment ∈ {'pos','neg','neu'}
    返回: {
        'foods':       {'pos': Counter, 'neg': Counter},
        'attractions': {'pos': Counter, 'neg': Counter},
        'places':      {'pos': Counter, 'neg': Counter},
    }
    """
    result = {
        "foods":       {"pos": Counter(), "neg": Counter()},
        "attractions": {"pos": Counter(), "neg": Counter()},
        "places":      {"pos": Counter(), "neg": Counter()},
    }
    for t, sent in texts_with_sentiment:
        if not t or sent == "neu":
            continue
        for m in FOOD_HINTS.findall(t):
            result["foods"][sent][m] += 1
        for m in ATTRACTION_HINTS.findall(t):
            result["attractions"][sent][m] += 1
        for word, _flag in pseg.cut(t):
            word = word.strip()
            if word in SHOP_DICT_SET:
                result["places"][sent][word] += 1
        for m in PLACE_NAME.findall(t):
            name = m.strip()
            if name in SHOP_DICT_SET:
                continue
            if _is_valid_shop_suffix(name):
                result["places"][sent][name] += 1
    return result


def length_stats(comments: list[dict]) -> dict:
    by_source = {"bili": [], "xhs": []}
    for c in comments:
        by_source[c["source"]].append(len(c["content"]))
    out = {}
    for src, lens in by_source.items():
        if not lens:
            out[src] = None
            continue
        lens_sorted = sorted(lens)
        n = len(lens_sorted)
        out[src] = {
            "n": n,
            "min": lens_sorted[0],
            "max": lens_sorted[-1],
            "median": median(lens_sorted),
            "p90": lens_sorted[int(n * 0.9)] if n > 1 else lens_sorted[0],
            "mean": sum(lens_sorted) / n,
        }
    return out


def ad_score(text: str) -> tuple[int, list[str]]:
    if not text:
        return 0, []
    hits = []
    score = 0
    kw = AD_RE.findall(text)
    if kw:
        hits.append(f"kw:{','.join(set(kw))}")
        score += 2 * len(set(kw))
    if URL_RE.search(text):
        hits.append("url")
        score += 3
    emoji_n = len(EMOJI_RE.findall(text))
    if emoji_n >= 5:
        hits.append(f"emoji:{emoji_n}")
        score += 1
    if len(text) > 60 and len(set(text)) / len(text) < 0.35:
        hits.append("repetitive")
        score += 2
    return score, hits


import math


def wilson_neg_lower(pos: int, neg: int, z: float = 1.96) -> float:
    """差评率的 Wilson Score 置信下界（95% 置信度）。

    返回值越高，说明该实体"真实差评率"越可信地高。
    pos/neg 都为 0 时返回 0。
    """
    n = pos + neg
    if n == 0:
        return 0.0
    p = neg / n  # 观察到的差评率
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (center - spread) / denom)


def neg_ratio(pos: int, neg: int) -> float:
    """差评率 = neg / (pos + neg)，无数据返回 0。"""
    total = pos + neg
    return neg / total if total > 0 else 0.0


def nss(pos: int, neg: int) -> float:
    """Net Sentiment Score = (pos - neg) / (pos + neg)，范围 [-1, +1]。"""
    total = pos + neg
    return (pos - neg) / total if total > 0 else 0.0


def flag_ads(items: list[dict], text_key: str) -> list[dict]:
    out = []
    for it in items:
        score, hits = ad_score(it.get(text_key) or "")
        if score >= 3:
            out.append({**it, "ad_score": score, "ad_hits": ";".join(hits)})
    return out


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    with db() as conn:
        posts, comments = load_texts(conn)

    print(f"[data] posts={len(posts)} comments={len(comments)}", file=sys.stderr)
    post_texts = [(p.get("title") or "") + "\n" + (p.get("content") or "") for p in posts]
    comment_texts = [c["content"] for c in comments]
    all_texts = post_texts + comment_texts

    places, foods, attractions = extract_names(all_texts)
    print("\n=== 高频提名 ===")
    print(f"店名类 top{args.top}:")
    for name, n in places.most_common(args.top):
        print(f"  {n:>3}  {name}")
    print(f"\n小吃/菜 top{args.top}:")
    for name, n in foods.most_common(args.top):
        print(f"  {n:>3}  {name}")
    print(f"\n景点 top{args.top}:")
    for name, n in attractions.most_common(args.top):
        print(f"  {n:>3}  {name}")

    print("\n=== 评论长度分布 ===")
    stats = length_stats(comments)
    for src, s in stats.items():
        if s:
            print(f"  {src}: n={s['n']} min={s['min']} median={s['median']:.0f} p90={s['p90']} max={s['max']} mean={s['mean']:.1f}")
        else:
            print(f"  {src}: (empty)")

    print("\n=== 疑似广告 ===")
    post_ads = flag_ads(posts, "content") + flag_ads(posts, "title")
    cmt_ads = flag_ads(comments, "content")
    print(f"  posts flagged: {len(post_ads)} / {len(posts)}")
    print(f"  comments flagged: {len(cmt_ads)} / {len(comments)}")
    if cmt_ads[:5]:
        print("  样例评论:")
        for c in cmt_ads[:5]:
            preview = c["content"][:60].replace("\n", " ")
            print(f"    [score={c['ad_score']} {c['ad_hits']}] {preview}")

    write_csv(OUT_DIR / "places.csv",
              [{"name": n, "count": c} for n, c in places.most_common()],
              ["name", "count"])
    write_csv(OUT_DIR / "foods.csv",
              [{"name": n, "count": c} for n, c in foods.most_common()],
              ["name", "count"])
    write_csv(OUT_DIR / "attractions.csv",
              [{"name": n, "count": c} for n, c in attractions.most_common()],
              ["name", "count"])
    write_csv(OUT_DIR / "ads_posts.csv", post_ads,
              ["id", "source", "title", "ad_score", "ad_hits"])
    write_csv(OUT_DIR / "ads_comments.csv", cmt_ads,
              ["id", "post_id", "source", "content", "ad_score", "ad_hits"])
    print(f"\n[out] CSV 写入 {OUT_DIR}")


if __name__ == "__main__":
    main()
