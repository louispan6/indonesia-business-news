# OpenClaw 印尼商业新闻自动化脚本

这个脚本会抓取 CNBC Indonesia 与 ANTARA 的 RSS 新闻源，筛选今日最新新闻，调用 DeepSeek API 生成中文商业简报，并保存为 Markdown 文件。

## 目录结构

```text
openclaw_id_news/
├── main.py
├── requirements.txt
├── .env.example
└── outputs/
```

`outputs/` 会在首次运行时自动创建。

## Ubuntu 22.04 / WSL2 初始化

```bash
cd /mnt/d/sister/openclaw_id_news

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

## 配置 DeepSeek 环境变量

```bash
cp .env.example .env
nano .env
```

`.env` 示例：

```env
DEEPSEEK_API_KEY=sk-your-deepseek-api-key-here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

脚本会通过 `python-dotenv` 自动加载 `.env`：

```python
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("DEEPSEEK_API_KEY")
```

DeepSeek 使用 OpenAI-compatible API，所以依赖仍然是 `openai` Python SDK。

## 运行

先测试 RSS 抓取，不调用 AI：

```bash
python main.py --fetch-only
```

确认能抓到新闻后，运行完整流程：

```bash
python main.py
```

生成文件示例：

```text
outputs/OpenClaw_ID_News_20260602.md
```

如果 DeepSeek 返回 `402 Insufficient Balance`，说明 API Key 有效但账户余额不足。脚本会自动把候选新闻保存为：

```text
outputs/OpenClaw_ID_News_Raw_YYYYMMDD.md
```

充值或更换可用 API Key 后，重新运行 `python main.py` 即可生成 AI 简报。

如果 CNBC Indonesia RSS 返回 `403 Forbidden`，通常是该站对请求做了拦截；脚本会继续使用 ANTARA 新闻源，不影响后续 AI 分析。

## RSS 源

- CNBC Indonesia News: `https://www.cnbcindonesia.com/news/rss`
- ANTARA Ekonomi: `https://www.antaranews.com/rss/ekonomi.xml`
- ANTARA Bisnis: `https://www.antaranews.com/rss/ekonomi-bisnis.xml`
