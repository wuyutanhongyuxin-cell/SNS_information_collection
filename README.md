# 西安旅行攻略 · 社交媒体语料分析库

**用途**：私人使用，去广告辨真用。不公开、不商用、不再分发。

从 Bilibili 和小红书采集西安旅游/美食相关帖子及评论，进行情感分析、实体抽取、广告检测，生成可视化报告。

---

## 环境要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | 3.12+ | 分析脚本 |
| [uv](https://docs.astral.sh/uv/) | 最新 | Python 包管理 / 运行器 |
| Node.js | 18+ | CLI 工具运行环境 |
| xiaohongshu-cli | 0.6.4 | 小红书数据采集 |
| bilibili-cli | 0.6.2 | B站数据采集 |

## 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/wuyutanhongyuxin-cell/SNS_information_collection.git
cd SNS_information_collection
```

### 2. 安装 Python 依赖

```bash
# 方式 A：用 uv（推荐）
uv run --python 3.12 --with jieba scripts/init_db.py

# 方式 B：用 pip
pip install -r requirements.txt
```

### 3. 安装 CLI 工具

```bash
# 安装 uv（如果没有）
# Windows: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
# macOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh

# 安装 CLI
uv tool install xiaohongshu-cli
uv tool install bilibili-cli
```

### 4. 初始化数据库

```bash
uv run --python 3.12 scripts/init_db.py
```

> 如果仓库里已包含 `data/corpus.db`，跳过此步。

---

## 数据采集

### B站采集（匿名，主力数据源）

B站**无需登录**，匿名即可搜索和拉评论。

```bash
# 单关键词采集
uv run --python 3.12 --with jieba scripts/fetch_bili.py --keyword "西安 美食" --limit 30

# 20 个关键词批量采集（约需 2-3 小时）
uv run --python 3.12 --with jieba scripts/batch_fetch_bili.py
```

**关键细节（踩坑经验）：**

- CLI 的 `bili video <bvid> --comments` 只返回 3 条评论（SDK bug，未传 `ps` 参数）
- `fetch_bili.py` 已改用 `/x/v2/reply/main` HTTP API 直接拉评论，支持游标分页，每页 20 条
- 批量采集每个关键词有 600s 超时，超时后已采数据仍会保存
- 如需对已有视频补抓评论：`uv run --python 3.12 --with jieba scripts/refetch_comments.py --max-pages 5`

### 小红书采集（需登录，样本补充）

小红书**必须登录**，cookie 约 24 小时过期。

```bash
# 第一步：登录（每天采集前必做）
xhs -v login --qrcode
# 终端会显示二维码，用小红书 App 扫码

# 检查登录状态
xhs status

# 单关键词采集
uv run --python 3.12 --with jieba scripts/fetch_xhs.py --keyword "西安 美食 避雷" --limit 20
```

**关键细节（踩坑经验）：**

- **`-v` 必须放在子命令前面**：`xhs -v login --qrcode`（不是 `xhs login -v --qrcode`）
- 不加 `-v` 可能触发 Camoufox 错误：`Failed to load Xiaohongshu login page in Camoufox`
- **Cookie 约 24 小时过期**，每天开始采集前先 `xhs status` 检查
- 每日限流 ≤ 150 条帖子，脚本内置 3-8s jitter + 每 20 条停 10-30s

### 关键词池

```
西安 美食 / 小吃 / 特产 / 踩雷 / 避雷
西安 三日游 / 攻略 / 行程 / 冷门
西安 住宿 / 民宿 / 酒店
西安 回民街 / 洒金桥 / 大唐不夜城
西安 烤肉 / 泡馍 / 肉夹馍 / 凉皮
陕博 预约 / 城墙 骑行 / 华山
西安 美食 踩雷 / 景点 排雷 / 夜市 小吃
```

---

## 分析 & 报告

### 运行分析

```bash
# 命令行输出统计摘要 + 生成 CSV
uv run --python 3.12 --with jieba scripts/analyze.py

# 生成可视化报告（自包含 HTML，双击即开）
uv run --python 3.12 --with jieba scripts/build_report.py
# 产出：data/analysis/report.html
```

### 报告包含

- **概览**：帖子/评论量、平台分布、关键词桑基图
- **美食排行**：高频食物 + 情感对比（好评金 vs 差评铜）+ NSS 排行
- **景点排行**：同上
- **店名排行**：jieba + 70+ 自定义词典抽取 + 情感分析
- **评论分布**：Bili vs XHS 评论长度直方图
- **广告检测**：基于关键词/链接/emoji 密度的广告嫌疑评分
- **明细表**：全部帖子可筛选浏览

### 情感分析说明

- 基于**知网 HowNet 情感词典**（8,800+ 词）：`data/lexicons/` 下 4 个文件
- **jieba 分词** → 逐词匹配正/负面词典 → 否定词翻转极性
- 补充了 20+ 美食/旅游领域词（避雷、踩雷、真香、难吃 等）
- 三项指标：**NSS**（净情感分）、**差评率**、**Wilson Score 置信下界**（修正小样本偏差）

### 店名 NER 说明

- `analyze.py` 内置 `XIAN_SHOP_DICT`：70+ 西安餐饮实体（烤肉/泡馍/面馆/陕菜 等）
- 用 `jieba.add_word()` 注册后精确匹配，不靠正则猜测
- 发现新店名时直接加入 `XIAN_SHOP_DICT` 列表即可

---

## 目录结构

```
data/
  corpus.db              SQLite 主库（WAL 模式）
  analysis/
    report.html          自包含可视化报告（双击打开）
    *.csv                分析导出
  lexicons/              知网 HowNet 情感词典（UTF-8）
    pos_emotion.txt      正面情感词 836 词
    pos_eval.txt         正面评价词 3730 词
    neg_emotion.txt      负面情感词 1254 词
    neg_eval.txt         负面评价词 3116 词
    negation.txt         否定词 30 词
raw/
  bili/                  B站原始 JSON 快照
  xhs/                   小红书原始 JSON 快照
scripts/
  common.py              公共配置（DB路径、限流、日志）
  init_db.py             初始化数据库表结构
  fetch_bili.py          B站单关键词采集
  batch_fetch_bili.py    B站 20 关键词批量采集
  fetch_xhs.py           小红书采集
  refetch_comments.py    补抓已有视频的评论
  analyze.py             文本分析（情感/NER/广告检测）
  build_report.py        生成 HTML 报告
  report_template.html   报告模板
logs/
  fetch.log              采集日志（时间+平台+数量）
```

## 限流规则

| 平台 | 日上限 | Jitter | 长停顿 |
|------|--------|--------|--------|
| 小红书 | 150 帖/天 | 3-8s | 每 20 帖停 10-30s |
| B站 | 无硬限 | 1-3s | 5% 概率停 10-30s |

## 定向补采策略

分析完成后，对 Wilson Score 低置信的实体做定向数据增强，提高结果可靠性：

1. **筛选目标**：从报告中找出 `neg=0 且 pos >= 5` 的实体（有一定好评量但零差评，统计上不可信）
2. **生成搜索词**：为每个实体生成定向搜索词，例如：
   - `"北广济街 踩雷"` / `"北广济街 避雷"` / `"北广济街 难吃"`
   - `"贾三 差评"` / `"贾三 不推荐"`
3. **专项搜索**：用这些词在 Bili + XHS 上做专项搜索，补充差评样本
4. **重新生成**：合并新数据后重新运行 `build_report.py`，更新 NSS / Wilson Score

> 零差评大概率是样本不足而非真无差评。定向补采后 Wilson Score 才有统计意义。

---

## 常见问题

**Q: 小红书登录失败 / Camoufox 错误？**
A: 确保用 `xhs -v login --qrcode`（`-v` 在 `login` 前面）。

**Q: B站评论只有 3 条？**
A: 如果你直接用 `bili video <bvid> --comments`，确实只有 3 条。`fetch_bili.py` 已改用 `/x/v2/reply/main` API，无需担心。

**Q: 两个脚本同时跑报 "database is locked"？**
A: SQLite WAL 模式 + 30s busy timeout 已处理绝大部分并发。偶发锁冲突会跳过该条并记录日志，不影响整体。避免同时运行两个写脚本即可。

**Q: 只想看报告不想采数据？**
A: 直接双击 `data/analysis/report.html`，零依赖，任何浏览器都能打开。
