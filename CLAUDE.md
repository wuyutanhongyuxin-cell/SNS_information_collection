# 项目上下文 — 给 Claude Code 的操作指南

本项目从 Bilibili 和小红书采集西安旅游/美食语料，进行情感分析和可视化。以下是开发过程中积累的关键经验，**请严格遵守**。

## 运行环境

- Python 3.12，通过 `uv run --python 3.12 --with jieba` 运行脚本
- SQLite 数据库：`data/corpus.db`（WAL 模式，30s busy timeout）
- CLI 工具：`xhs`（xiaohongshu-cli 0.6.4）、`bili`（bilibili-cli 0.6.2）

## CLI 工具关键用法

### 小红书 CLI（xhs）

- **登录命令**：`xhs -v login --qrcode`
  - `-v` 是**全局选项**，必须放在子命令 `login` **前面**
  - 不加 `-v` 会走 Camoufox 浏览器方式，可能报 `Failed to load Xiaohongshu login page in Camoufox`
  - 终端内直接显示二维码，用小红书 App 扫码
- **Cookie 有效期约 24 小时**，每天采集前必须先 `xhs status` 检查登录状态
- 常用命令：
  - `xhs status` — 检查登录状态
  - `xhs search "关键词" --page 1 --json` — 搜索笔记
  - `xhs read <note_id> --json --xsec-token <token>` — 读取笔记详情
  - `xhs comments <note_id> --all --json --xsec-token <token>` — 获取所有评论
- **每日限流**：≤ 150 条帖子，脚本内置 3-8s jitter

### Bilibili CLI（bili）

- **匿名即可使用**，无需登录
- `bili search "关键词" --type video --max N --json` — 搜索视频
- `bili video <bvid> --json` — 获取视频详情
- **已知 bug**：`bili video <bvid> --comments --json` 只返回 3 条评论（SDK 层 `comment.py:465` 未传 `ps` 参数）
  - **解决方案**：`fetch_bili.py` 已改用 `/x/v2/reply/main` HTTP API 直接拉评论
  - 该 API 支持游标分页（`pagination_str.offset`），匿名每页 20 条
  - 不要试图修复 CLI 本身，直接用 HTTP API

## 数据采集注意事项

- **不要同时运行两个写数据库的脚本**，SQLite 并发写会偶发 "database is locked"
- 批量采集（`batch_fetch_bili.py`）每个关键词有 600s 超时，超时后已采数据仍会保存
- 补抓评论：`uv run --python 3.12 --with jieba scripts/refetch_comments.py --max-pages 5`
- 所有原始 JSON 都保存在 `raw/{bili,xhs}/` 下，数据库损坏时可重建

## 分析模块注意事项

### 情感分析（analyze.py）

- 基于**知网 HowNet 情感词典**（`data/lexicons/` 下 4 个文件 + 1 个否定词表）
- 算法：jieba 分词 → 逐词匹配正/负面词典 → 否定词翻转下一个情感词极性
- 已补充 20+ 美食/旅游领域词（避雷、踩雷、真香、难吃 等）
- 搜索关键词含"避雷/踩雷/排雷"时自动给负面加权 +2
- 三项指标：
  - **NSS** = (pos-neg)/(pos+neg)，范围 [-1, +1]
  - **差评率** = neg/(pos+neg)
  - **Wilson Score 置信下界** — 修正小样本偏差（95% 置信度）

### 店名 NER（analyze.py）

- `XIAN_SHOP_DICT`：70+ 西安餐饮实体，通过 `jieba.add_word()` 注册
- 发现新店名时直接加入该列表即可
- 后缀正则兜底只用高精度后缀：记/坊/斋/轩/苑/堂/铺/屋/庄/面馆 等
- 已去掉噪声大的后缀：店/馆/楼/园/院

## 报告生成（build_report.py）

- `uv run --python 3.12 --with jieba scripts/build_report.py`
- 产出 `data/analysis/report.html`（自包含，双击即开）
- 模板在 `scripts/report_template.html`，用 `/*__DATA_JSON__*/{}` 做占位替换

## 可视化注意事项（report_template.html）

- **ECharts diverging bar**：正负两个 series 必须用**相同的 `stack` 名**
  - 错误：`stack:'sent'` 和 `stack:'sent2'` → 会分成两行
  - 正确：两个都用 `stack:'sentiment'` → 同一行左右对称
- 设计风格是**香槟金奢侈品风**（champagne gold editorial），配色务必用金色系：
  - 好评 / 正面：香槟金 `#E8D095`（dark）/ `#A8873E`（light）
  - 差评 / 负面：氧化铜 `#7A4530`（dark）/ `#6B3A22`（light）
  - NSS 渐变：从暗铜（差）到明金（好），不要用红绿彩虹色
- 切勿引入与金色系不协调的颜色（纯红、纯绿、蓝色等）

## 文件下载注意

- **不要用 WebFetch 下载中文词典等 GBK 编码文件**，会乱码或被拒绝返回
- 改用 `curl -sL <url> -o <file>` 下载到本地，再用 Python 指定编码（gbk/gb2312/gb18030）读取转 UTF-8

## 目标数据比例

- Bili 与 XHS 帖子量比约 10-15:1（Bili 为主力数据源，XHS 做补充）
- 当前：Bili 721 帖 / XHS 47 帖 ≈ 15.3:1

## 定向补采策略（待实施）

分析完成后，对 `neg=0 且 pos >= 5` 的实体做定向搜索：
- 为每个实体生成搜索词：`"{实体名} 踩雷"` / `"{实体名} 避雷"` / `"{实体名} 难吃"`
- 在 Bili + XHS 上专项搜索，补充差评样本
- 目的：提高 Wilson Score 对这些实体的置信度
