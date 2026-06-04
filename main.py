import argparse
import html
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import feedparser
import requests
from dotenv import load_dotenv
from openai import APIStatusError, OpenAI


SYSTEM_PROMPT = """
# 角色设定
你是一位常驻雅加达的资深商业分析师，专门为中国出海企业家、跨境电商卖家和外贸从业者提供高价值的印尼市场情报。

# 任务目标
我将提供一批今日印尼新闻的原始标题和摘要（印尼语或英语）。你的任务是：
1. 【毒辣筛选】从繁杂的资讯中，挑选出最具商业变现价值、宏观指导意义的 3-5 条核心新闻。
2. 【重构翻译】将选出的新闻转化为符合中国顶尖财经媒体排版习惯的中文简报。

# 筛选标准（核心护城河）
- 必须优先选择：政策法规变动、宏观经济指标、重点行业动向（如新能源、电商新规、基建）。
- 坚决过滤：本地社会治安事件、政党口水战、娱乐八卦、无实质数据的企业公关稿。

# 翻译与输出规范（迎合中国商人阅读习惯）
1. 严禁输出任何寒暄、解释、确认语或元叙述，例如“好的，老板”“已为您筛选”“以下是”等。
2. 第一行必须直接输出 Markdown 二级标题：## 今日印尼市场情报简报（YYYY年M月D日）
3. 每条新闻必须配一张图片：如果候选新闻提供 Image URL，必须在标题下方输出 `![图片说明](Image URL)`。
4. 标题重构：必须前置“核心数据”或“关键动作”，让人一眼看透利好还是利空。
5. 结构化输出：每条新闻严格按以下三段式输出：
   - `### [序号]. [提炼后的硬核标题，加适当 Emoji]`
   - `**商业资讯：** [80-100字极度精炼概括新闻核心事实，保留重要数据]`
   - `**出海洞察：** [一句话点透这条新闻对中国商人的直接影响，如合规成本、清关风险、投资机会等]`
6. 不要使用项目符号列表；每条新闻之间空一行。
"""


RSS_SOURCES = [
    {
        "source": "CNBC Indonesia News",
        "url": "https://www.cnbcindonesia.com/news/rss",
    },
    {
        "source": "ANTARA Ekonomi",
        "url": "https://www.antaranews.com/rss/ekonomi.xml",
    },
    {
        "source": "ANTARA Bisnis",
        "url": "https://www.antaranews.com/rss/ekonomi-bisnis.xml",
    },
]


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def get_text(self) -> str:
        return " ".join(self.parts)


def clean_html(raw_text: str | None) -> str:
    """Remove HTML tags/entities and collapse extra whitespace."""
    if not raw_text:
        return ""

    extractor = _HTMLTextExtractor()
    extractor.feed(html.unescape(raw_text))
    text = extractor.get_text()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_image_url(entry: Any) -> str:
    """Extract a representative image URL from common RSS fields."""
    for field in ("media_content", "media_thumbnail"):
        media_items = entry.get(field) or []
        for media_item in media_items:
            image_url = (media_item.get("url") or "").strip()
            if image_url:
                return image_url

    for enclosure in entry.get("enclosures") or []:
        image_url = (enclosure.get("href") or enclosure.get("url") or "").strip()
        media_type = (enclosure.get("type") or "").lower()
        if image_url and (not media_type or media_type.startswith("image/")):
            return image_url

    for link_item in entry.get("links") or []:
        image_url = (link_item.get("href") or "").strip()
        media_type = (link_item.get("type") or "").lower()
        rel = (link_item.get("rel") or "").lower()
        if image_url and (media_type.startswith("image/") or rel == "enclosure"):
            return image_url

    raw_summary = (
        entry.get("summary")
        or entry.get("description")
        or entry.get("subtitle")
        or ""
    )
    image_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw_summary, re.I)
    if image_match:
        return html.unescape(image_match.group(1)).strip()

    return ""


def parse_entry_datetime(entry: Any, fallback_tz: ZoneInfo) -> datetime:
    """Parse common RSS datetime fields into timezone-aware datetime."""
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed_value = entry.get(field)
        if parsed_value:
            return datetime(*parsed_value[:6], tzinfo=timezone.utc).astimezone(fallback_tz)

    for field in ("published", "updated", "created"):
        raw_value = entry.get(field)
        if raw_value:
            try:
                parsed_dt = parsedate_to_datetime(raw_value)
                if parsed_dt.tzinfo is None:
                    parsed_dt = parsed_dt.replace(tzinfo=fallback_tz)
                return parsed_dt.astimezone(fallback_tz)
            except (TypeError, ValueError):
                continue

    return datetime.now(fallback_tz)


def fetch_feed(source_name: str, rss_url: str, timeout: int = 20) -> list[dict[str, Any]]:
    print(f"🚀 正在抓取 {source_name} 新闻源...")
    headers = {
        "User-Agent": "OpenClaw-ID-NewsBot/1.0 (+https://openclaw.local)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    response = requests.get(rss_url, headers=headers, timeout=timeout)
    response.raise_for_status()

    parsed_feed = feedparser.parse(response.content)
    if parsed_feed.bozo:
        print(f"⚠️  {source_name} RSS 解析存在警告，继续尝试读取可用条目。")

    entries: list[dict[str, Any]] = []
    jakarta_tz = ZoneInfo("Asia/Jakarta")

    for entry in parsed_feed.entries:
        published_at = parse_entry_datetime(entry, jakarta_tz)
        title = clean_html(entry.get("title", ""))
        link = entry.get("link", "").strip()
        summary = clean_html(
            entry.get("summary")
            or entry.get("description")
            or entry.get("subtitle")
            or ""
        )
        image_url = extract_image_url(entry)

        if not title or not link:
            continue

        entries.append(
            {
                "source": source_name,
                "title": title,
                "link": link,
                "summary": summary,
                "image_url": image_url,
                "published_at": published_at.isoformat(timespec="seconds"),
                "published_date": published_at.date().isoformat(),
            }
        )

    print(f"📥 {source_name} 获取到 {len(entries)} 条原始新闻。")
    return entries


def fetch_indonesia_news(max_items: int = 20, min_items: int = 15) -> list[dict[str, str]]:
    """Fetch today's latest Indonesia business news from configured RSS sources."""
    jakarta_tz = ZoneInfo("Asia/Jakarta")
    today = datetime.now(jakarta_tz).date()
    collected: list[dict[str, Any]] = []

    for source in RSS_SOURCES:
        try:
            collected.extend(fetch_feed(source["source"], source["url"]))
        except requests.RequestException as exc:
            print(f"⚠️  {source['source']} 抓取失败：{exc}")

    if not collected:
        raise RuntimeError("没有抓取到任何新闻，请检查网络、RSS 地址或代理设置。")

    unique_by_link: dict[str, dict[str, Any]] = {}
    for item in collected:
        unique_by_link[item["link"]] = item

    sorted_items = sorted(
        unique_by_link.values(),
        key=lambda item: item["published_at"],
        reverse=True,
    )

    todays_items = [
        item for item in sorted_items
        if datetime.fromisoformat(item["published_at"]).date() == today
    ]

    if len(todays_items) >= min_items:
        selected = todays_items[:max_items]
        print(f"✅ 今日新闻满足数量要求，选取 {len(selected)} 条。")
    else:
        selected = sorted_items[:max_items]
        print(
            f"⚠️  今日新闻仅 {len(todays_items)} 条，已补充最近新闻至 {len(selected)} 条。"
        )

    return [
        {
            "source": item["source"],
            "title": item["title"],
            "link": item["link"],
            "summary": item["summary"],
            "image_url": item["image_url"],
            "published_at": item["published_at"],
        }
        for item in selected
    ]


def format_news_for_ai(news_data: list[dict[str, str]]) -> str:
    lines = [
        "以下是今日抓取到的印尼新闻候选列表，请按系统要求筛选、翻译并重构："
    ]
    for index, item in enumerate(news_data, start=1):
        lines.append(
            "\n".join(
                [
                    f"\n{index}. 来源：{item['source']}",
                    f"发布时间：{item['published_at']}",
                    f"Title：{item['title']}",
                    f"Link：{item['link']}",
                    f"Summary：{item['summary'] or '无摘要'}",
                    f"Image URL：{item.get('image_url') or '无'}",
                ]
            )
        )
    return "\n".join(lines)


def clean_ai_content(content: str) -> str:
    """Remove model preambles before the first actual Markdown heading."""
    stripped = content.strip()
    heading_match = re.search(r"(?m)^(#{1,3}\s+.+)$", stripped)
    if heading_match:
        return stripped[heading_match.start():].strip()

    numbered_match = re.search(r"(?m)^\s*1[.、]\s+", stripped)
    if numbered_match:
        return stripped[numbered_match.start():].strip()

    return stripped


def process_news_with_ai(news_data: list[dict[str, str]]) -> str:
    if not news_data:
        raise ValueError("news_data 为空，无法交由 AI 分析。")

    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    if not api_key:
        raise RuntimeError("未检测到 DEEPSEEK_API_KEY，请先在 .env 文件中配置。")

    client = OpenAI(api_key=api_key, base_url=base_url)
    news_text = format_news_for_ai(news_data)

    print(f"🧠 正在交由 DeepSeek AI 分析筛选，模型：{model} ...")
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.3,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": news_text},
            ],
        )
    except APIStatusError as exc:
        if exc.status_code == 402:
            raise RuntimeError(
                "DeepSeek API 余额不足，请先到 DeepSeek 控制台充值或更换可用 API Key。"
            ) from exc
        raise RuntimeError(
            f"DeepSeek API 调用失败：HTTP {exc.status_code}，{exc.message}"
        ) from exc

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("AI 返回内容为空。")

    return clean_ai_content(content)


def save_to_markdown(content: str) -> Path:
    posts_dir = Path("_posts")
    posts_dir.mkdir(parents=True, exist_ok=True)

    beijing_now = datetime.now(ZoneInfo("Asia/Shanghai"))
    post_date = beijing_now.strftime("%Y-%m-%d")
    post_time = beijing_now.strftime("%H%M%S")
    post_title = f"印尼商业风向标：{post_date} 今日简报"
    filename = f"{post_date}-indonesia-news-{post_time}.md"
    output_path = posts_dir / filename

    front_matter = "\n".join(
        [
            "---",
            "layout: post",
            f'title: "{post_title}"',
            f"date: {beijing_now.strftime('%Y-%m-%d %H:%M:%S %z')}",
            "categories: [indonesia, business, news]",
            "tags: [印尼, 商业情报, 宏观经济, 出海]",
            "---",
            "",
        ]
    )
    output_path.write_text(front_matter + content.strip() + "\n", encoding="utf-8")
    return output_path


def save_raw_news_to_markdown(news_data: list[dict[str, str]]) -> Path:
    output_dir = Path("outputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    beijing_today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
    output_path = output_dir / f"OpenClaw_ID_News_Raw_{beijing_today}.md"

    lines = [
        f"# OpenClaw 印尼候选新闻原始列表 - {beijing_today}",
        "",
        "AI 处理失败时自动保存。可在 DeepSeek 余额恢复后重新运行完整流程。",
        "",
    ]
    for index, item in enumerate(news_data, start=1):
        lines.extend(
            [
                f"## {index}. {item['title']}",
                "",
                f"- 来源：{item['source']}",
                f"- 发布时间：{item['published_at']}",
                f"- 链接：{item['link']}",
                f"- 摘要：{item['summary'] or '无摘要'}",
                f"- 图片：{item.get('image_url') or '无'}",
                "",
            ]
        )

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="抓取印尼商业新闻，调用 AI 筛选翻译，并保存为 Markdown 简报。"
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="只抓取 RSS 新闻并打印结果，不调用 AI。",
    )
    args = parser.parse_args()

    print("====== OpenClaw 印尼商业新闻自动化脚本 ======")
    print("🚀 正在抓取印尼商业新闻...")
    news_data = fetch_indonesia_news()
    print(f"✅ 已整理 {len(news_data)} 条候选新闻。")

    if args.fetch_only:
        print("\n以下为抓取结果预览：")
        for index, item in enumerate(news_data, start=1):
            print(f"{index}. [{item['source']}] {item['title']}")
            print(f"   {item['link']}")
        return

    try:
        content = process_news_with_ai(news_data)
    except RuntimeError as exc:
        raw_output_path = save_raw_news_to_markdown(news_data)
        print(f"❌ AI 处理失败：{exc}")
        print(f"📝 已先保存候选新闻原始列表：{raw_output_path}")
        raise SystemExit(1) from exc

    output_path = save_to_markdown(content)
    print(f"✅ 简报已生成：{output_path}")


if __name__ == "__main__":
    main()
