# NHK Easy News 每日自动抓取

每天 UTC 0:00 (北京时间 8:00 / 东京时间 9:00) 自动从 [NHK Easy News](https://www3.nhk.or.jp/news/easy/) 抓当日文章, 转成 app 数据格式, commit 到本仓库. 你的 PWA 在用户打开时自动 fetch 最新数据, 合并到 `JP_DATA.N3.newsList` 顶部, 显示"📰 今日 NHK 速递"横幅.

## 架构

```
┌─────────────────┐    cron 每天跑     ┌────────────────────┐
│  GitHub Actions │ ───────────────→  │  fetch_nhk.py      │
│  (ubuntu-latest)│                   │  + format_data.py  │
└─────────────────┘                    └──────────┬─────────┘
                                                  │
                                  commit + push   │
                                                  ▼
                                     ┌────────────────────────┐
                                     │  data/nhk-app-format.json
                                     └──────────┬─────────────┘
                                                │
                                                │ raw.githubusercontent.com
                                                ▼
                                  ┌──────────────────────────┐
                                  │  你的 PWA (index.html)   │
                                  │  启动时 fetch + 合并     │
                                  │  → N3 newsList 顶部     │
                                  └──────────────────────────┘
```

**为什么用 GitHub Actions 而不是 mavis cron?** 之前我们试过 mavis 沙箱里跑 cron 抓 NHK, 失败 — 沙箱的 IP 段被 NHK 屏蔽. GitHub Actions 跑在 Azure 数据中心, 不受这个限制.

---

## 部署步骤 (用户只需 3 步, ~5 分钟)

### 第 1 步: 创建 GitHub 仓库

1. 登录 GitHub
2. 打开 https://github.com/new
3. 填仓库名: `nhk-easy-daily` (或你喜欢的名字)
4. 选 **Public** (这样 raw.githubusercontent.com 可以直接访问, 不用配 token)
5. **不要**勾选 "Add a README" / "Add .gitignore" / "Choose a license" (我们用本地代码)
6. 点 "Create repository"
7. 复制仓库的 SSH URL, 类似 `git@github.com:YOUR_USERNAME/nhk-easy-daily.git`

### 第 2 步: 推送代码 (告诉 agent, 帮你推)

回到对话, 把刚才复制的 URL 发给我, 我会帮你:

```bash
cd nhk-pipeline/
git init
git remote add origin <你的仓库 URL>
git add .
git commit -m "init: NHK daily fetcher"
git push -u origin main
```

(或者你自己跑也行, 上面的命令就 4 行)

### 第 3 步: 启用 GitHub Actions + 第一次跑

1. 在 GitHub 仓库页面, 点 **Actions** 标签
2. 如果提示启用, 点 "I understand my workflows, go ahead and enable them"
3. 左侧选 **Daily NHK Easy News**
4. 右侧点 **Run workflow** 按钮 → 选 main 分支 → 点绿色 "Run workflow"
5. 等 1-2 分钟, 看是否成功
6. 成功后仓库根目录的 `data/nhk-app-format.json` 应该有了内容

**首次跑通后**, 每天 UTC 0:00 (北京时间 8:00) 会自动跑, 不用再管.

### 第 4 步: 告诉 agent 你的仓库地址, 我帮你接入 PWA

把仓库 URL (例如 `https://github.com/YOUR_USERNAME/nhk-easy-daily`) 发给我, 我会:

1. 把 URL 写进 `prototype/nhk-daily.js` 的 `NHK_DAILY_URL`
2. 重新部署 PWA
3. 你打开 PWA, 切到 N3 等级, news-list 顶部应该出现 "📰 今日 NHK 速递" 横幅

---

## 文件结构

```
nhk-pipeline/
├── .github/
│   └── workflows/
│       └── daily-nhk.yml        # GitHub Actions 定时任务
├── scripts/
│   ├── fetch_nhk.py             # 抓取 NHK Easy News HTML
│   └── format_data.py           # 转成 app 数据格式
├── data/                        # 输出目录 (git tracked)
│   ├── nhk-today.json           # 原始抓取数据
│   └── nhk-app-format.json      # app 格式 (PWA fetch 这个)
├── examples/
│   └── sample.json              # 输出样例 (没真实抓过时的 mock)
├── requirements.txt             # Python 依赖
└── README.md                    # 本文件
```

## 本地测试 (可选)

```bash
cd nhk-pipeline/
pip install -r requirements.txt

# 跑一次抓取
python scripts/fetch_nhk.py --output data/nhk-today.json

# 转成 app 格式
python scripts/format_data.py --input data/nhk-today.json --output data/nhk-app-format.json
```

## 故障排查

### Actions 跑失败: "fetch_nhk.py: NHK request timeout"

- **原因**: 极小概率, 偶尔 GitHub Actions runner 也会被 NHK 临时屏蔽
- **解决**: 不管, 第二天会自动重试. 或者手动 Re-run workflow.

### Actions 跑成功, 但 PWA 不显示横幅

- 检查 `data/nhk-app-format.json` 是否有内容
- 检查浏览器 Console: 应该有 `[NHK daily] loaded fresh: N items` 日志
- 检查 `prototype/nhk-daily.js` 的 `NHK_DAILY_URL` 是否正确

### 抓取内容是空的 articles 数组

- NHK 周末不发新闻, 抓取会空. 周一到周五应该都有 3-5 篇.

## 限制

- **翻译**: 当前 `title_zh` 留空, UI 显示"查看英文版" 链接 (跳到 NHK 英文版同篇文章). 后续可以接入 GPT 翻译.
- **等级**: 所有抓到的文章默认归到 N3 (NHK Easy News 的难度). 后续可以做 N1-N5 自动分级.
- **音频**: NHK 的 m3u8 音频 URL 会保存到 `audioUrl` 字段, 但 app 当前没用到 (TTS 兜底).

## 进阶: 接入翻译 (可选)

在 GitHub repo → Settings → Secrets and variables → Actions → New repository secret, 添加:

- `OPENAI_API_KEY` = 你的 OpenAI key

修改 `format_data.py`, 在 `article_to_news_dict` 里调用:

```python
# 伪代码
if os.environ.get('OPENAI_API_KEY'):
    title_zh = call_gpt(article['title'], target='zh')
    body_zh = [call_gpt(p) for p in body_paragraphs]
```

(后续可以加这个, 不在初版里)

---

## 备注

- 抓取脚本参考了 [nhk-news-web-easy/nhk-easy-task](https://github.com/nhk-news-web-easy/nhk-easy-task) 和 [nhk-news-fetcher-go](https://github.com/nhk-news-web-easy/nhk-news-fetcher-go) 的数据 schema
- 但**没用 OAuth 也没用第三方 API**, 直接抓 HTML, 依赖少
- 如果 NHK 改了页面结构, 需要相应更新 selector
