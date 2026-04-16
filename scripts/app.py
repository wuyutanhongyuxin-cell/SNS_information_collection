"""西安语料分析台 · Streamlit Dashboard

启动：
    uv run --with streamlit --with plotly --with pandas --with wordcloud \
           --with streamlit-extras --with streamlit-option-menu \
           --python 3.12 streamlit run app.py
"""
from __future__ import annotations

import io
import re
from collections import Counter
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from wordcloud import WordCloud

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
)
from common import ROOT, db

try:
    from streamlit_option_menu import option_menu
    HAS_OPTION_MENU = True
except ImportError:
    HAS_OPTION_MENU = False

CN_FONT = "C:/Windows/Fonts/msyh.ttc"
if not Path(CN_FONT).exists():
    CN_FONT = None

# =============================================================================
# 样式 & 全局配置
# =============================================================================
st.set_page_config(
    page_title="西安语料分析台",
    page_icon="🏯",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
    .block-container {padding-top: 1.5rem; max-width: 1400px;}
    h1, h2, h3 {letter-spacing: -0.02em;}
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, rgba(99,102,241,0.08), rgba(236,72,153,0.05));
        border: 1px solid rgba(148,163,184,0.12);
        border-radius: 14px;
        padding: 18px 20px;
    }
    div[data-testid="stMetric"] label {
        color: #94a3b8 !important; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        font-size: 2.1rem; font-weight: 700;
    }
    section[data-testid="stSidebar"] {background: #0b1220;}
    .title-row {display:flex; align-items:baseline; gap:16px; margin-bottom:0.2rem;}
    .title-row h1 {margin:0; font-size:2.2rem;}
    .title-row .sub {color:#94a3b8; font-size:0.9rem;}
    .badge {display:inline-block; padding:2px 10px; border-radius:999px;
            font-size:0.72rem; font-weight:600; margin-right:6px;}
    .badge.bili {background:#fb7185; color:white;}
    .badge.xhs {background:#f97316; color:white;}
    .badge.both {background:#6366f1; color:white;}
    .tag {display:inline-block; padding:2px 8px; border-radius:6px;
          font-size:0.7rem; margin-right:4px; background:rgba(99,102,241,0.15); color:#a5b4fc;}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

PLOTLY_TEMPLATE = "plotly_dark"
PALETTE_FOOD = px.colors.sequential.Sunsetdark
PALETTE_SPOT = px.colors.sequential.Tealgrn
PALETTE_PLACE = px.colors.sequential.Plasma


# =============================================================================
# 数据加载
# =============================================================================
@st.cache_data(show_spinner="加载语料中…")
def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    with db() as conn:
        posts = pd.read_sql(
            "SELECT id, source, source_id, post_type, title, content, "
            "likes, comments_count, url, keyword, fetched_at "
            "FROM posts",
            conn,
        )
        comments = pd.read_sql(
            "SELECT c.id, c.post_id, c.content, c.likes, c.fetched_at, "
            "p.source, p.keyword "
            "FROM comments c JOIN posts p ON p.id = c.post_id "
            "WHERE c.content IS NOT NULL AND length(c.content) > 0",
            conn,
        )
    posts["title"] = posts["title"].fillna("")
    posts["content"] = posts["content"].fillna("")
    posts["keyword"] = posts["keyword"].fillna("(无)")
    posts["text"] = posts["title"] + "\n" + posts["content"]
    comments["content"] = comments["content"].fillna("")
    comments["clen"] = comments["content"].str.len()
    comments["likes"] = comments["likes"].fillna(0).astype(int)
    return posts, comments


def count_names(texts: list[str]) -> tuple[Counter, Counter, Counter]:
    places, foods, attractions = Counter(), Counter(), Counter()
    for t in texts:
        if not t:
            continue
        for m in PLACE_NAME.findall(t):
            name = m.strip()
            if 2 <= len(name) <= 12 and name not in PLACE_STOPWORDS and not PLACE_BLACKLIST.match(name):
                places[name] += 1
        for m in FOOD_HINTS.findall(t):
            foods[m] += 1
        for m in ATTRACTION_HINTS.findall(t):
            attractions[m] += 1
    return places, foods, attractions


def build_wordcloud_png(counter: Counter, top_n: int = 80) -> bytes | None:
    if not counter:
        return None
    items = dict(counter.most_common(top_n))
    wc = WordCloud(
        font_path=CN_FONT,
        width=1100,
        height=420,
        background_color="#0e1117",
        colormap="plasma",
        prefer_horizontal=0.95,
        relative_scaling=0.5,
    ).generate_from_frequencies(items)
    buf = io.BytesIO()
    wc.to_image().save(buf, format="PNG")
    return buf.getvalue()


# =============================================================================
# 页面：顶栏 & 侧栏筛选
# =============================================================================
posts_all, comments_all = load_data()

st.markdown(
    f"""
<div class='title-row'>
  <h1>🏯 西安语料分析台</h1>
  <span class='sub'>小红书 + B 站 · 真实口碑信号 · 私人分析</span>
</div>
<div style='margin-bottom:1rem; color:#64748b; font-size:0.85rem;'>
  语料库快照：<b>{len(posts_all)}</b> 帖 · <b>{len(comments_all)}</b> 评论 ·
  覆盖 <b>{posts_all['keyword'].nunique()}</b> 个关键词 ·
  数据路径 <code>data/corpus.db</code>
</div>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### 🎚️ 筛选器")
    sources = st.multiselect(
        "数据源",
        options=sorted(posts_all["source"].unique()),
        default=sorted(posts_all["source"].unique()),
        format_func=lambda s: {"bili": "B 站", "xhs": "小红书"}.get(s, s),
    )
    keywords = st.multiselect(
        "关键词",
        options=sorted(posts_all["keyword"].unique()),
        default=sorted(posts_all["keyword"].unique()),
    )
    min_likes = st.slider("帖子最小点赞数", 0, int(max(posts_all["likes"].fillna(0).max(), 1)), 0, step=50)
    top_n = st.slider("榜单 Top N", 5, 40, 15)

    st.markdown("---")
    st.caption("📦 当前筛选")

    posts_df = posts_all[
        posts_all["source"].isin(sources)
        & posts_all["keyword"].isin(keywords)
        & (posts_all["likes"].fillna(0) >= min_likes)
    ].copy()
    comments_df = comments_all[
        comments_all["source"].isin(sources)
        & comments_all["keyword"].isin(keywords)
        & comments_all["post_id"].isin(posts_df["id"])
    ].copy()

    st.metric("帖子", len(posts_df), delta=f"{len(posts_df) - len(posts_all)}" if len(posts_df) != len(posts_all) else None)
    st.metric("评论", len(comments_df))

if posts_df.empty:
    st.warning("当前筛选结果为空，调整侧栏参数试试。")
    st.stop()


# =============================================================================
# Tab 导航
# =============================================================================
TABS = ["📊 概览", "🍜 美食榜", "🏛️ 景点榜", "🏪 店名提名", "💬 评论分析", "🎭 广告识别", "🔎 原始浏览"]
if HAS_OPTION_MENU:
    active = option_menu(
        None,
        TABS,
        icons=["grid-3x3-gap", "egg-fried", "building", "shop", "chat-left-dots", "shield-exclamation", "search"],
        orientation="horizontal",
        default_index=0,
        styles={
            "container": {"padding": "0!important", "background-color": "transparent"},
            "nav-link": {"font-size": "0.92rem", "text-align": "center", "margin": "0 2px", "--hover-color": "#1e293b"},
            "nav-link-selected": {"background-color": "#6366f1", "font-weight": "600"},
        },
    )
else:
    active = st.radio("导航", TABS, horizontal=True, label_visibility="collapsed")


# =============================================================================
# 共享计算
# =============================================================================
all_texts = posts_df["text"].tolist() + comments_df["content"].tolist()
places_c, foods_c, attractions_c = count_names(all_texts)


def rank_bar(counter: Counter, title: str, palette, n: int, orient_h: bool = True):
    items = counter.most_common(n)
    if not items:
        st.info(f"{title}：没有命中项")
        return
    df = pd.DataFrame(items, columns=["名称", "频次"])
    if orient_h:
        fig = px.bar(
            df.iloc[::-1], x="频次", y="名称", orientation="h",
            color="频次", color_continuous_scale=palette, text="频次",
        )
        fig.update_traces(textposition="outside", textfont_size=12)
    else:
        fig = px.bar(df, x="名称", y="频次", color="频次", color_continuous_scale=palette, text="频次")
        fig.update_traces(textposition="outside")
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        title=title,
        title_font_size=16,
        height=max(320, 26 * n + 100) if orient_h else 360,
        margin=dict(l=10, r=10, t=50, b=10),
        coloraxis_showscale=False,
        yaxis_title="", xaxis_title="",
    )
    st.plotly_chart(fig, use_container_width=True)


def download_button(df: pd.DataFrame, label: str, filename: str):
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(label, csv, filename, "text/csv")


# =============================================================================
# TAB: 概览
# =============================================================================
if active == "📊 概览":
    k1, k2, k3, k4, k5 = st.columns(5)
    with k1: st.metric("📝 帖子", f"{len(posts_df):,}")
    with k2: st.metric("💬 评论", f"{len(comments_df):,}")
    with k3:
        per = len(comments_df) / max(len(posts_df), 1)
        st.metric("📈 评论/帖", f"{per:.1f}")
    with k4:
        st.metric("🏷️ 关键词", posts_df["keyword"].nunique())
    with k5:
        st.metric("📊 中位评论长度", f"{int(comments_df['clen'].median()) if len(comments_df) else 0}")

    st.markdown("#### 🔥 按来源分布")
    c1, c2 = st.columns([1, 1])
    with c1:
        by_src = posts_df.groupby("source").size().reset_index(name="帖子数")
        by_src["来源"] = by_src["source"].map({"bili": "B 站", "xhs": "小红书"})
        fig = px.pie(by_src, names="来源", values="帖子数", hole=0.55,
                     color_discrete_sequence=["#fb7185", "#f97316"])
        fig.update_layout(template=PLOTLY_TEMPLATE, height=340, title="帖子来源占比",
                          margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        by_kw = posts_df.groupby(["keyword", "source"]).size().reset_index(name="n")
        fig = px.bar(by_kw, x="keyword", y="n", color="source", barmode="group",
                     color_discrete_map={"bili": "#fb7185", "xhs": "#f97316"},
                     labels={"keyword": "关键词", "n": "帖子数", "source": "来源"})
        fig.update_layout(template=PLOTLY_TEMPLATE, height=340, title="关键词 × 来源",
                          margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### 🏆 三大榜单速览")
    tabs = st.tabs(["美食", "景点", "店名提名"])
    with tabs[0]: rank_bar(foods_c, "", PALETTE_FOOD, min(top_n, 10))
    with tabs[1]: rank_bar(attractions_c, "", PALETTE_SPOT, min(top_n, 10))
    with tabs[2]: rank_bar(places_c, "", PALETTE_PLACE, min(top_n, 10))


# =============================================================================
# TAB: 美食榜
# =============================================================================
elif active == "🍜 美食榜":
    st.markdown("### 🍜 美食榜 · 词频硬榜")
    c1, c2 = st.columns([3, 2])
    with c1:
        rank_bar(foods_c, "出现频次 Top N", PALETTE_FOOD, top_n)
    with c2:
        st.markdown("#### ☁️ 词云")
        png = build_wordcloud_png(foods_c)
        if png: st.image(png, use_container_width=True)
        else: st.info("词云为空")

    st.markdown("#### 🔬 双源对比")
    split = {}
    for src in sources:
        texts = (posts_df[posts_df["source"] == src]["text"].tolist()
                 + comments_df[comments_df["source"] == src]["content"].tolist())
        _, fc, _ = count_names(texts)
        split[src] = fc
    rows = []
    for food in foods_c.keys():
        rows.append({"美食": food, **{src: split[src].get(food, 0) for src in split}})
    df = pd.DataFrame(rows).set_index("美食").head(top_n)
    if not df.empty:
        fig = go.Figure()
        palette = {"bili": "#fb7185", "xhs": "#f97316"}
        for src in df.columns:
            fig.add_trace(go.Bar(name={"bili": "B 站", "xhs": "小红书"}.get(src, src),
                                 x=df.index, y=df[src], marker_color=palette.get(src, "#6366f1")))
        fig.update_layout(barmode="group", template=PLOTLY_TEMPLATE, height=380,
                          title="各来源提名次数", margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(fig, use_container_width=True)

    download_button(pd.DataFrame(foods_c.most_common(), columns=["美食", "频次"]),
                    "⬇️ 下载美食榜 CSV", "foods.csv")


# =============================================================================
# TAB: 景点榜
# =============================================================================
elif active == "🏛️ 景点榜":
    st.markdown("### 🏛️ 景点榜 · 提名热度")
    c1, c2 = st.columns([3, 2])
    with c1: rank_bar(attractions_c, "", PALETTE_SPOT, top_n)
    with c2:
        st.markdown("#### ☁️ 词云")
        png = build_wordcloud_png(attractions_c)
        if png: st.image(png, use_container_width=True)

    st.markdown("#### 📈 热度 vs 评论参与")
    rows = []
    for spot in attractions_c.keys():
        mask = (posts_df["text"].str.contains(spot, na=False, regex=False)
                | posts_df["id"].isin(comments_df[comments_df["content"].str.contains(spot, na=False, regex=False)]["post_id"]))
        related_posts = posts_df[mask]
        rows.append({
            "景点": spot,
            "提名次数": attractions_c[spot],
            "相关帖子": len(related_posts),
            "总点赞": int(related_posts["likes"].fillna(0).sum()),
        })
    scatter_df = pd.DataFrame(rows)
    if not scatter_df.empty:
        fig = px.scatter(scatter_df, x="提名次数", y="相关帖子", size="总点赞",
                         color="提名次数", hover_name="景点",
                         color_continuous_scale=PALETTE_SPOT, size_max=50)
        fig.update_layout(template=PLOTLY_TEMPLATE, height=460,
                          margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)
        download_button(scatter_df.sort_values("提名次数", ascending=False),
                        "⬇️ 下载景点榜 CSV", "attractions.csv")


# =============================================================================
# TAB: 店名提名
# =============================================================================
elif active == "🏪 店名提名":
    st.markdown("### 🏪 店名/机构 提名榜")
    st.caption("⚠️ 规则法抽取，有噪音。出现在多帖评论里的项更可信。")
    c1, c2 = st.columns([3, 2])
    with c1: rank_bar(places_c, "", PALETTE_PLACE, top_n)
    with c2:
        st.markdown("#### ☁️ 词云")
        png = build_wordcloud_png(places_c, top_n=60)
        if png: st.image(png, use_container_width=True)

    st.markdown("#### 🔎 搜索某个提名的原文上下文")
    candidates = [n for n, _ in places_c.most_common(top_n * 2)]
    if candidates:
        pick = st.selectbox("选一个提名", candidates)
        rows = []
        for _, c in comments_df.iterrows():
            if pick in c["content"]:
                rows.append({"来源": c["source"], "内容": c["content"][:120], "点赞": c["likes"]})
        for _, p in posts_df.iterrows():
            if pick in p["text"]:
                rows.append({"来源": p["source"], "内容": (p["title"] + " | " + p["content"])[:120], "点赞": int(p["likes"] or 0)})
        if rows:
            st.dataframe(pd.DataFrame(rows).sort_values("点赞", ascending=False).head(30),
                         use_container_width=True, hide_index=True)


# =============================================================================
# TAB: 评论分析
# =============================================================================
elif active == "💬 评论分析":
    st.markdown("### 💬 评论分析")
    c1, c2 = st.columns(2)
    with c1:
        fig = px.histogram(comments_df, x="clen", color="source", nbins=50,
                           color_discrete_map={"bili": "#fb7185", "xhs": "#f97316"},
                           labels={"clen": "评论长度（字符）", "source": "来源"})
        fig.update_layout(template=PLOTLY_TEMPLATE, height=400,
                          title="评论长度分布", margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.box(comments_df, x="source", y="clen", color="source", points=False,
                     color_discrete_map={"bili": "#fb7185", "xhs": "#f97316"},
                     labels={"clen": "评论长度", "source": "来源"})
        fig.update_layout(template=PLOTLY_TEMPLATE, height=400,
                          title="评论长度箱型图（log）", yaxis_type="log",
                          margin=dict(l=10, r=10, t=50, b=10))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### 🔥 热门评论 Top 20")
    hot = comments_df.sort_values("likes", ascending=False).head(20)[
        ["source", "keyword", "content", "likes", "clen"]
    ].rename(columns={"source": "来源", "keyword": "关键词", "content": "内容",
                      "likes": "点赞", "clen": "字数"})
    st.dataframe(hot, use_container_width=True, hide_index=True)
    download_button(comments_df[["source", "keyword", "content", "likes", "clen"]],
                    "⬇️ 下载全量评论 CSV", "comments_filtered.csv")


# =============================================================================
# TAB: 广告识别
# =============================================================================
elif active == "🎭 广告识别":
    st.markdown("### 🎭 疑似广告检测")
    st.caption("命中关键词、链接、过度 emoji、重复字符都会加分，≥3 标为可疑。")

    def score_row(text):
        s, h = ad_score(text)
        return pd.Series({"score": s, "hits": ";".join(h)})

    cmt_scored = comments_df.assign(**comments_df["content"].apply(score_row))
    post_scored = posts_df.assign(**(posts_df["title"] + " " + posts_df["content"]).apply(score_row))

    c1, c2, c3 = st.columns(3)
    with c1: st.metric("可疑评论", int((cmt_scored["score"] >= 3).sum()))
    with c2: st.metric("可疑帖子", int((post_scored["score"] >= 3).sum()))
    with c3:
        pct = 100 * (cmt_scored["score"] >= 3).mean() if len(cmt_scored) else 0
        st.metric("评论可疑率", f"{pct:.2f}%")

    st.markdown("#### 散点：评论长度 × 广告分 × 点赞")
    plot_df = cmt_scored[cmt_scored["score"] > 0].copy()
    if not plot_df.empty:
        fig = px.scatter(plot_df, x="clen", y="score", size=plot_df["likes"].clip(lower=1),
                         color="source", hover_data=["content", "hits"],
                         color_discrete_map={"bili": "#fb7185", "xhs": "#f97316"},
                         labels={"clen": "评论长度", "score": "广告分"})
        fig.update_layout(template=PLOTLY_TEMPLATE, height=460,
                          margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### 🚨 可疑评论清单")
    ads = cmt_scored[cmt_scored["score"] >= 3].sort_values("score", ascending=False).head(50)
    if not ads.empty:
        show = ads[["source", "keyword", "score", "hits", "content", "likes"]].rename(
            columns={"source": "来源", "keyword": "关键词", "score": "得分", "hits": "命中",
                     "content": "内容", "likes": "点赞"})
        st.dataframe(show, use_container_width=True, hide_index=True)
        download_button(ads, "⬇️ 下载可疑评论 CSV", "ads_comments.csv")
    else:
        st.info("没有命中可疑阈值的评论。")


# =============================================================================
# TAB: 原始浏览
# =============================================================================
elif active == "🔎 原始浏览":
    st.markdown("### 🔎 原始帖子浏览")
    search = st.text_input("🔍 全文搜索（标题/内容）", "")
    view = posts_df.copy()
    if search:
        view = view[view["text"].str.contains(search, case=False, na=False, regex=False)]
    view = view.sort_values("likes", ascending=False, na_position="last")
    st.caption(f"共 {len(view)} 条帖子")

    for _, p in view.head(30).iterrows():
        badge = f"<span class='badge {p['source']}'>{'B 站' if p['source']=='bili' else '小红书'}</span>"
        with st.expander(f"{'🎬' if p['source']=='bili' else '📝'} {p['title'][:80] or '(无标题)'}  ·  ❤️ {int(p['likes'] or 0)}"):
            st.markdown(
                f"{badge} <span class='tag'>{p['keyword']}</span> "
                f"<span class='tag'>💬 {int(p['comments_count'] or 0)}</span> "
                f"<a href='{p['url'] or '#'}' target='_blank'>🔗 原链接</a>",
                unsafe_allow_html=True,
            )
            if p["content"]:
                st.markdown(f"> {p['content'][:600]}")
            related = comments_df[comments_df["post_id"] == p["id"]].sort_values("likes", ascending=False).head(8)
            if not related.empty:
                st.markdown("**热门评论**")
                for _, c in related.iterrows():
                    st.markdown(f"- ❤️ {c['likes']} · {c['content'][:180]}")
