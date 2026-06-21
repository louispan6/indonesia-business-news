import argparse
import html
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import feedparser
import requests
from dotenv import load_dotenv
from openai import APIStatusError, OpenAI


BEIJING_TZ = timezone(timedelta(hours=8), name="UTC+08:00")
WECHAT_QR_IMAGE_URL = (
    "https://louispan6.github.io/indonesia-business-news/"
    "assets/images/wechat-qrcode.jpg"
)


def env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


OUTPUT_RULES = """
# 输出规范（死守中国出海企业视角）
1. 严禁输出任何寒暄、解释、确认语或元叙述，例如“好的，老板”“已为您筛选”“以下是”等。
2. 第一行必须直接输出 Markdown 二级标题：## 今日印尼市场情报简报（YYYY年M月D日）
3. 正文标题后必须先输出一段“今日内容导读”，早报和晚报都必须有。格式必须严格如下：
   - `### 今日内容导读`
   - 紧接着输出 5 条编号导读：`1. ...` 到 `5. ...`
   - 每条导读必须是一句短标题，控制在 18-28 个中文字符左右，必须包含关键数据、关键动作或风险信号。
   - 5 条导读的顺序必须与后文 5 条正文新闻一一对应，不得出现正文没有展开的导读。
   - 导读之后空一行，再开始正文第 1 条新闻。
4. 每条新闻必须配一张图片：如果候选新闻提供 Image URL，必须在标题下方紧跟一行 `![图片说明](Image URL)`。不要写“配图”“图片来源”等标签。
5. 标题重构：必须前置“核心数据”“关键动作”或“监管信号”，让人一眼看透利好、利空或风险方向。
6. 写作风格必须像正式商业情报报告，不要像填表，不要使用“重点：”“前因后果：”“主要内容：”“出海影响：”这类栏目标签。
7. 每条新闻必须写得具体，不能只写结论。必须自然交代重点、前因后果、主要内容和对中国出海企业的影响。
8. 每条新闻严格按以下文章式结构输出：
   - `### [序号]. [提炼后的硬核标题，加适当 Emoji]`
   - `![图片说明](Image URL)`
   - 第 1 段：用 120-180 字讲清新闻的核心事实、关键数据、涉及机构或动作，让读者快速知道发生了什么。
   - 第 2 段：用 160-240 字解释背景、政策脉络、利益相关方、为什么现在发生，以及后续可能如何演变。
   - 第 3 段：用 160-240 字具体展开对中国出海企业的影响，必须落到合规成本、清关/签证/税务风险、供应链成本、市场机会、渠道变化、政府项目或资产安全等具体维度。
   - 如信息量足够，可加第 4 段，补充操作建议或需要继续观察的信号。
9. 正文新闻不要使用项目符号列表；每条新闻之间空一行。导读区可以使用 1-5 编号列表。
10. 每篇简报的新闻条数以对应报告模式要求为准；每条必须有信息密度，不要写空泛概括。
"""


MORNING_SYSTEM_PROMPT = f"""
# 角色设定
你是一位常驻雅加达的政商与政策观察员。你的核心任务是预警政治、监管与本地政策变化，专门为中国出海企业家、跨境电商卖家和外贸从业者识别印尼政法、行政审批、地方治理和营商环境变化。

# 任务目标
我将提供一批今日印尼新闻的原始标题和摘要（印尼语或英语）。你的任务是：
1. 【强制风险过滤】从繁杂资讯中挑选最值得中国出海企业警惕的 5 条核心政经与政策新闻，必须正好输出 5 条，不得少于 5 条。
2. 【重构翻译】将选出的新闻转化为符合中国顶尖财经媒体排版习惯的中文政经风险简报。

# 早间政经内参强制筛选规则
- 早间财经内参必须固定输出 5 条。即使当天没有重大抓捕、反腐或执法新闻，也要从税务、海关、投资许可、地方政策、产业监管、财政预算、政府采购、劳工签证、能源物流和营商环境新闻中补足 5 条。
- 第一优先级：重点寻找包含以下机构或动作的新闻：移民局(Imigrasi)抓捕/遣返、反贪局(KPK)调查、海关(Bea Cukai)严查、部长级高官落马、针对外籍劳工(TKA)的新政。
- 第二优先级：如果当天没有足够重大的抓捕、反腐或执法新闻，必须主动转向筛选对营商环境有影响的印尼本地政策新闻，包括税务征管、劳工监管、签证/居留、进口许可、海关流程、地方政府许可、政府采购、产业园区、土地/环保审批、能源价格、物流交通、数字政务、投资便利化、地方最低工资和中小企业政策。
- 第三优先级：如果没有全国性大政策，也可以选择省市级政策、政府部门执行口径、行业监管口径和官方经济治理信号，但必须说明它为什么会影响中国企业的市场进入、合规成本、供应链安全或本地化经营。
- 必须优先选择：政府突发监管、贪腐调查、官员落马、外籍劳工政策、海关稽查、签证/居留审查、政府招标风向、外资审批变化、地方营商政策、财政税务执行口径、投资许可变化和对外企资产安全有影响的事件。
- 每条新闻必须直接回答：这件事会如何影响中国出海企业的工作签证、外籍员工、海关清关、税务稽查、政府项目、资产安全、本地合作伙伴和合规成本。
- 如果抓取到的新闻全是软性的会议通稿或政客口水战，请优先寻找其中是否包含政策执行、预算方向、监管权限、许可流程、地方治理或产业资源配置变化；仍然没有实质信息时再过滤。
- 不要只盯“谁被抓”。普通抓捕新闻如果不能引出移民、海关、反腐、招投标、外劳、资产安全或企业合规影响，应当过滤。
- 坚决过滤：无政策含义的普通会议通稿、政客表态、无监管动作的口水战、单纯刑事案件、娱乐八卦、没有外溢商业风险或经营含义的地方新闻。

{OUTPUT_RULES}
"""


EVENING_SYSTEM_PROMPT = f"""
# 角色设定
你是一位常驻雅加达的宏观经济分析师，专门为中国出海企业家、跨境电商卖家和外贸从业者提供高价值的印尼市场与产业情报。

# 任务目标
我将提供一批今日印尼新闻的原始标题和摘要（印尼语或英语）。你的任务是：
1. 【毒辣筛选】从繁杂资讯中挑选最值得中国出海企业关注的 5 条核心新闻，必须正好输出 5 条，不得少于 5 条。
2. 【重构翻译】将选出的新闻转化为符合中国顶尖财经媒体排版习惯的中文简报。

# 晚间市场观察筛选标准
- 晚间市场观察必须固定输出 5 条新闻。每条必须有明确数据、产业含义或市场影响，不得用同一事件、同一政策或同一行业口径拆成多条凑数。
- 重点筛选：宏观经济数据（汇率、通胀、贸易、财政）、民生消费热点、重点产业动态（如新能源、电商、基建、制造业、物流、矿业和农业）。
- 必须深度剖析这些【民生与经济数据】对中国出海企业的直接影响，例如国民消费力降级、特定赛道爆发、供应链成本涨跌、清关风险、渠道价格变化和投资窗口。
- 如果候选新闻与最近几天已写过的主题高度相似，除非有新的关键数据、政策动作、监管升级或产业变化，否则必须跳过，改选其他领域新闻。
- 坚决过滤：娱乐八卦、单纯社会治安事件、没有数据或产业含义的企业公关稿。

{OUTPUT_RULES}
"""


MORNING_RSS_SOURCES = [
    {
        "source": "Detik Hukum",
        "url": "https://news.detik.com/hukum/rss",
    },
    {
        "source": "Detik Nasional",
        "url": "https://news.detik.com/berita/rss",
    },
    {
        "source": "Kompas Nasional",
        "url": "https://nasional.kompas.com/rss",
    },
    {
        "source": "CNN Indonesia Nasional",
        "url": "https://www.cnnindonesia.com/nasional/rss",
    },
    {
        "source": "ANTARA Hukum",
        "url": "https://www.antaranews.com/rss/hukum.xml",
    },
    {
        "source": "ANTARA Politik",
        "url": "https://www.antaranews.com/rss/politik.xml",
    },
    {
        "source": "ANTARA Terkini",
        "url": "https://www.antaranews.com/rss/terkini.xml",
    },
    {
        "source": "ANTARA Ekonomi",
        "url": "https://www.antaranews.com/rss/ekonomi.xml",
    },
    {
        "source": "Sekretariat Kabinet RI",
        "url": "https://setkab.go.id/feed/",
    },
    {
        "source": "Tempo Nasional",
        "url": "https://rss.tempo.co/nasional",
    },
    {
        "source": "Kontan Nasional",
        "url": "https://nasional.kontan.co.id/rss",
    },
    {
        "source": "Kontan Keuangan",
        "url": "https://keuangan.kontan.co.id/rss",
    },
    {
        "source": "Tempo Bisnis",
        "url": "https://rss.tempo.co/bisnis",
    },
    {
        "source": "Kompas Money",
        "url": "https://money.kompas.com/rss",
    },
]


EVENING_RSS_SOURCES = [
    {
        "source": "CNBC Indonesia News",
        "url": "https://www.cnbcindonesia.com/news/rss",
    },
    {
        "source": "Detik Finance",
        "url": "https://finance.detik.com/rss",
    },
    {
        "source": "CNN Indonesia Ekonomi",
        "url": "https://www.cnnindonesia.com/ekonomi/rss",
    },
    {
        "source": "ANTARA Ekonomi",
        "url": "https://www.antaranews.com/rss/ekonomi.xml",
    },
    {
        "source": "ANTARA Bisnis",
        "url": "https://www.antaranews.com/rss/ekonomi-bisnis.xml",
    },
    {
        "source": "ANTARA Terkini",
        "url": "https://www.antaranews.com/rss/terkini.xml",
    },
    {
        "source": "Tempo Bisnis",
        "url": "https://rss.tempo.co/bisnis",
    },
    {
        "source": "Kompas Money",
        "url": "https://money.kompas.com/rss",
    },
    {
        "source": "Bisnis Indonesia Ekonomi",
        "url": "https://ekonomi.bisnis.com/rss",
    },
    {
        "source": "Kontan Keuangan",
        "url": "https://keuangan.kontan.co.id/rss",
    },
    {
        "source": "Kontan Industri",
        "url": "https://industri.kontan.co.id/rss",
    },
    {
        "source": "Kontan Investasi",
        "url": "https://investasi.kontan.co.id/rss",
    },
    {
        "source": "Kontan Nasional",
        "url": "https://nasional.kontan.co.id/rss",
    },
    {
        "source": "Okezone Economy",
        "url": "https://economy.okezone.com/rss",
    },
    {
        "source": "Liputan6 Bisnis",
        "url": "https://www.liputan6.com/rss/bisnis",
    },
    {
        "source": "Republika Ekonomi",
        "url": "https://ekonomi.republika.co.id/rss",
    },
]


def get_beijing_now() -> datetime:
    return datetime.now(BEIJING_TZ)


def get_run_context() -> dict[str, Any]:
    beijing_now = get_beijing_now()
    return {
        "beijing_now": beijing_now,
        "current_bj_date": beijing_now.strftime("%Y-%m-%d"),
        "current_bj_datetime": beijing_now.strftime("%Y-%m-%d %H:%M:%S"),
        "current_bj_time": beijing_now.strftime("%H%M%S"),
    }


def get_report_profile(run_context: dict[str, Any]) -> dict[str, Any]:
    beijing_now = run_context["beijing_now"]
    is_morning = beijing_now.hour < 14

    if is_morning:
        return {
            "kind": "morning",
            "label": "早间政经内参",
            "filename_prefix": "morning",
            "rss_sources": MORNING_RSS_SOURCES,
            "system_prompt": MORNING_SYSTEM_PROMPT,
            "required_item_count": 5,
        }

    return {
        "kind": "evening",
        "label": "晚间市场观察",
        "filename_prefix": "evening",
        "rss_sources": EVENING_RSS_SOURCES,
        "system_prompt": EVENING_SYSTEM_PROMPT,
        "required_item_count": 5,
    }


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


def fetch_article_image_url(article_url: str, timeout: int = 10) -> str:
    """Fetch article page and extract Open Graph/Twitter image URL."""
    if not article_url:
        return ""

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        response = requests.get(article_url, headers=headers, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException:
        return ""

    page_html = response.text
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
        r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)["\']',
    ]

    for pattern in patterns:
        image_match = re.search(pattern, page_html, re.I)
        if image_match:
            return urljoin(article_url, html.unescape(image_match.group(1)).strip())

    return ""


def parse_entry_datetime(entry: Any, fallback_tz: timezone) -> datetime | None:
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

    return None


def normalize_for_dedupe(text: str) -> str:
    return re.sub(r"\W+", "", text.lower())


def normalize_url_for_dedupe(url: str) -> str:
    return url.strip().rstrip("/")


def fetch_feed(source_name: str, rss_url: str, timeout: int = 20) -> list[dict[str, Any]]:
    print(f"🚀 正在抓取 {source_name} 新闻源...")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    response = requests.get(rss_url, headers=headers, timeout=timeout)
    response.raise_for_status()

    parsed_feed = feedparser.parse(response.content)
    if parsed_feed.bozo:
        print(f"⚠️  {source_name} RSS 解析存在警告，继续尝试读取可用条目。")

    entries: list[dict[str, Any]] = []

    for entry in parsed_feed.entries:
        published_at = parse_entry_datetime(entry, BEIJING_TZ)
        if published_at is None:
            continue

        title = clean_html(entry.get("title", ""))
        link = entry.get("link", "").strip()
        summary = clean_html(
            entry.get("summary")
            or entry.get("description")
            or entry.get("subtitle")
            or ""
        )
        image_url = extract_image_url(entry)
        if not image_url:
            image_url = fetch_article_image_url(link)

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


def fetch_indonesia_news(
    rss_sources: list[dict[str, str]],
    current_bj_date: str,
    exclude_links: set[str] | None = None,
    max_items: int = 36,
    min_items: int = 15,
    per_source_limit: int = 5,
) -> list[dict[str, str]]:
    """Fetch today's latest Indonesia news from configured RSS sources.

    The source list is intentionally broader than the final candidate count. To
    avoid one high-volume RSS feed crowding out policy or finance sources, this
    first keeps a small number of fresh items from each source, then fills any
    remaining slots with the newest items overall.
    """
    collected: list[dict[str, Any]] = []

    for source in rss_sources:
        try:
            collected.extend(fetch_feed(source["source"], source["url"]))
        except requests.RequestException as exc:
            print(f"⚠️  {source['source']} 抓取失败：{exc}")

    if not collected:
        raise RuntimeError("没有抓取到任何新闻，请检查网络、RSS 地址或代理设置。")

    normalized_exclude_links = {
        normalize_url_for_dedupe(link) for link in (exclude_links or set())
    }
    unique_by_link: dict[str, dict[str, Any]] = {}
    seen_titles: set[str] = set()
    for item in collected:
        normalized_link = normalize_url_for_dedupe(item["link"])
        if normalized_link in normalized_exclude_links:
            continue

        normalized_title = normalize_for_dedupe(item["title"])
        if normalized_title in seen_titles:
            continue
        seen_titles.add(normalized_title)
        unique_by_link[normalized_link] = item

    sorted_items = sorted(
        unique_by_link.values(),
        key=lambda item: item["published_at"],
        reverse=True,
    )

    todays_items = [
        item for item in sorted_items
        if datetime.fromisoformat(item["published_at"]).date().isoformat() == current_bj_date
    ]
    print(
        f"🧮 去重后剩余 {len(sorted_items)} 条；其中 {current_bj_date} "
        f"未发布过的当天新闻 {len(todays_items)} 条。"
    )

    if not todays_items:
        raise RuntimeError(
            f"{current_bj_date} 没有抓取到未发布过的当天新闻，已停止生成，避免重复发布旧闻。"
        )

    by_source: dict[str, list[dict[str, Any]]] = {}
    for item in todays_items:
        by_source.setdefault(item["source"], []).append(item)

    selected_by_link: dict[str, dict[str, Any]] = {}
    for source in rss_sources:
        source_name = source["source"]
        for item in by_source.get(source_name, [])[:per_source_limit]:
            selected_by_link[normalize_url_for_dedupe(item["link"])] = item
            if len(selected_by_link) >= max_items:
                break
        if len(selected_by_link) >= max_items:
            break

    if len(selected_by_link) < max_items:
        for item in todays_items:
            selected_by_link[normalize_url_for_dedupe(item["link"])] = item
            if len(selected_by_link) >= max_items:
                break

    selected = sorted(
        selected_by_link.values(),
        key=lambda item: item["published_at"],
        reverse=True,
    )[:max_items]

    if len(todays_items) < min_items:
        print(
            f"⚠️  今日新闻仅 {len(todays_items)} 条，将严格只使用当天新闻，不补旧闻。"
        )
    else:
        print(f"✅ 今日新闻满足数量要求，已按来源平衡选取 {len(selected)} 条。")

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


def load_recent_post_links(
    current_bj_date: str,
    report_profile: dict[str, Any],
    max_days: int = 7,
) -> set[str]:
    posts_dir = Path("_posts")
    if not posts_dir.exists():
        return set()

    current_date = datetime.strptime(current_bj_date, "%Y-%m-%d").date()
    earliest_date = current_date - timedelta(days=max_days)
    filename_marker = f"-{report_profile['filename_prefix']}-"
    links: set[str] = set()

    for post_path in sorted(posts_dir.glob("*.md"), reverse=True):
        if filename_marker not in post_path.name:
            continue

        date_match = re.match(r"(\d{4}-\d{2}-\d{2})-", post_path.name)
        if not date_match:
            continue

        post_date = datetime.strptime(date_match.group(1), "%Y-%m-%d").date()
        if post_date >= current_date or post_date < earliest_date:
            continue

        try:
            post_text = post_path.read_text(encoding="utf-8")
        except OSError:
            continue

        for raw_link in re.findall(r"https?://[^\s)\]]+", post_text):
            links.add(normalize_url_for_dedupe(raw_link))

    return links


def load_recent_post_headlines(
    current_bj_date: str,
    report_profile: dict[str, Any],
    max_days: int = 7,
    limit: int = 30,
) -> list[str]:
    posts_dir = Path("_posts")
    if not posts_dir.exists():
        return []

    current_date = datetime.strptime(current_bj_date, "%Y-%m-%d").date()
    earliest_date = current_date - timedelta(days=max_days)
    filename_marker = f"-{report_profile['filename_prefix']}-"
    headlines: list[str] = []

    for post_path in sorted(posts_dir.glob("*.md"), reverse=True):
        if filename_marker not in post_path.name:
            continue

        date_match = re.match(r"(\d{4}-\d{2}-\d{2})-", post_path.name)
        if not date_match:
            continue

        post_date = datetime.strptime(date_match.group(1), "%Y-%m-%d").date()
        if post_date >= current_date or post_date < earliest_date:
            continue

        try:
            post_text = post_path.read_text(encoding="utf-8")
        except OSError:
            continue

        for line in post_text.splitlines():
            if not line.startswith("### "):
                continue
            headline = re.sub(r"^###\s*\d+[.、]\s*", "", line).strip()
            if headline:
                headlines.append(headline)
            if len(headlines) >= limit:
                return headlines

    return headlines


def format_news_for_ai(
    news_data: list[dict[str, str]],
    recent_headlines: list[str] | None = None,
) -> str:
    lines = [
        "以下是今日抓取到的印尼新闻候选列表，请按系统要求筛选、翻译并重构："
    ]
    if recent_headlines:
        lines.extend(
            [
                "",
                "以下是最近几天同类简报已经写过的标题。除非候选新闻出现实质新进展、关键数字变化或监管动作升级，否则不要重复选择这些旧主题：",
            ]
        )
        for index, headline in enumerate(recent_headlines, start=1):
            lines.append(f"{index}. {headline}")

        lines.append("")
        lines.append("注意：不要把同一个事件、同一政策、同一机构动作、同一行业口径拆成多条不同标题。")
        lines.append("")

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


def build_system_prompt(
    base_prompt: str,
    current_bj_date: str,
    required_item_count: int | None = None,
) -> str:
    count_rule = ""
    if required_item_count is not None:
        count_rule = (
            "\n\n# 条数强制规则\n"
            f"本次简报必须正好输出 {required_item_count} 条新闻。"
            f"标题编号必须从 1 到 {required_item_count}，不得少于或多于该数量。"
            f"“今日内容导读”也必须正好输出 {required_item_count} 条，并与正文新闻顺序一一对应。"
            "如果硬风险新闻不足，请用政策、财政、税务、海关、投资许可、地方营商环境、产业监管或政府采购类新闻补足。"
        )

    return (
        f"{base_prompt}\n\n"
        "# 日期一致性强制规则\n"
        f"今天是 {current_bj_date}。请在生成简报正文的开头严格使用这个具体日期，"
        "绝不允许随意编造历史时间、未来时间或与该日期不一致的日期。"
        f"{count_rule}"
    )


def process_news_with_ai(
    news_data: list[dict[str, str]],
    system_prompt: str,
    current_bj_date: str,
    recent_headlines: list[str] | None = None,
    required_item_count: int | None = None,
) -> str:
    if not news_data:
        raise ValueError("news_data 为空，无法交由 AI 分析。")

    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    if not api_key:
        raise RuntimeError("未检测到 DEEPSEEK_API_KEY，请先在 .env 文件中配置。")

    client = OpenAI(api_key=api_key, base_url=base_url)
    news_text = format_news_for_ai(news_data, recent_headlines)
    final_system_prompt = build_system_prompt(
        system_prompt,
        current_bj_date,
        required_item_count,
    )

    print(f"🧠 正在交由 DeepSeek AI 分析筛选，模型：{model} ...")
    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.3,
            max_tokens=6000,
            messages=[
                {"role": "system", "content": final_system_prompt},
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


def save_to_markdown(
    content: str,
    report_profile: dict[str, Any],
    run_context: dict[str, Any],
    news_data: list[dict[str, str]],
) -> Path:
    posts_dir = Path("_posts")
    posts_dir.mkdir(parents=True, exist_ok=True)

    beijing_now = run_context["beijing_now"]
    post_date = run_context["current_bj_date"]
    post_time = run_context["current_bj_time"]
    post_title = f"印尼商业风向标：{post_date} [{report_profile['label']}]"
    filename = (
        f"{post_date}-{report_profile['filename_prefix']}"
        f"-indonesia-news-{post_time}.md"
    )
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

    source_audit_lines = [
        "<!--",
        "source_candidates:",
    ]
    for item in news_data:
        source_audit_lines.append(
            f"- {item['source']} | {item['published_at']} | {item['title']} | {item['link']}"
        )
    source_audit_lines.extend(["-->", ""])
    source_audit = "\n".join(source_audit_lines)
    follow_section = "\n".join(
        [
            "### 关注公众号",
            "",
            "关注公众号，持续接收印尼市场、政策监管与出海商业情报。",
            "",
            f"![扫码关注公众号]({WECHAT_QR_IMAGE_URL})",
        ]
    )

    output_path.write_text(
        front_matter + content.strip() + "\n\n" + follow_section + "\n\n" + source_audit + "\n",
        encoding="utf-8",
    )
    return output_path


def save_raw_news_to_markdown(
    news_data: list[dict[str, str]],
    run_context: dict[str, Any],
) -> Path:
    output_dir = Path("outputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    beijing_today = run_context["current_bj_date"].replace("-", "")
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


def push_to_github(output_path: Path) -> dict[str, Any]:
    if not env_flag("GITHUB_PUSH_ENABLED"):
        return {"enabled": False, "status": "skipped"}

    github_token = os.getenv("GITHUB_TOKEN")
    github_username = os.getenv("GITHUB_USERNAME")
    github_repo = os.getenv("GITHUB_REPO")
    missing_envs = [
        name
        for name, value in {
            "GITHUB_TOKEN": github_token,
            "GITHUB_USERNAME": github_username,
            "GITHUB_REPO": github_repo,
        }.items()
        if not value
    ]
    if missing_envs:
        raise RuntimeError(
            "已开启 GITHUB_PUSH_ENABLED，但缺少环境变量："
            + ", ".join(missing_envs)
        )

    branch = os.getenv("GITHUB_BRANCH", "main")
    remote_url = f"https://{github_token}@github.com/{github_username}/{github_repo}.git"
    commit_message = os.getenv(
        "GITHUB_COMMIT_MESSAGE",
        f"chore: publish Indonesia brief {output_path.name}",
    )

    commands = [
        ["git", "config", "--global", "user.name", os.getenv("GIT_AUTHOR_NAME", "OpenClaw Bot")],
        [
            "git",
            "config",
            "--global",
            "user.email",
            os.getenv("GIT_AUTHOR_EMAIL", "openclaw-bot@users.noreply.github.com"),
        ],
        ["git", "remote", "set-url", "origin", remote_url],
        ["git", "add", str(output_path)],
        ["git", "commit", "-m", commit_message],
        ["git", "pull", "--rebase", "origin", branch],
        ["git", "push", "origin", branch],
    ]

    for command in commands:
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        if command[:2] == ["git", "commit"] and result.returncode != 0:
            combined_output = f"{result.stdout}\n{result.stderr}".lower()
            if "nothing to commit" in combined_output or "no changes added" in combined_output:
                return {"enabled": True, "status": "no_changes"}

        if result.returncode != 0:
            safe_command = [
                part.replace(github_token, "***") if github_token else part
                for part in command
            ]
            safe_stdout = result.stdout.replace(github_token, "***")
            safe_stderr = result.stderr.replace(github_token, "***")
            raise RuntimeError(
                f"GitHub 推送步骤失败：{' '.join(safe_command)}\n"
                f"stdout: {safe_stdout}\nstderr: {safe_stderr}"
            )

    return {
        "enabled": True,
        "status": "pushed",
        "branch": branch,
        "repo": f"{github_username}/{github_repo}",
    }


def publish_to_wechat(output_path: Path) -> dict[str, Any]:
    if not env_flag("WECHAT_PUBLISH_ENABLED"):
        return {"enabled": False, "status": "skipped"}

    try:
        from wechat_publisher import publish_markdown_to_wechat
    except ImportError as exc:
        raise RuntimeError(
            "已开启 WECHAT_PUBLISH_ENABLED，但没有找到 wechat_publisher.py "
            "或 publish_markdown_to_wechat()。"
        ) from exc

    result = publish_markdown_to_wechat(output_path)
    if isinstance(result, dict):
        return {"enabled": True, **result}
    return {"enabled": True, "status": "published", "result": result}


def run_daily_job(fetch_only: bool = False) -> dict[str, Any]:
    load_dotenv()

    run_context = get_run_context()
    report_profile = get_report_profile(run_context)
    print("====== OpenClaw 印尼商业新闻自动化脚本 ======")
    print(f"🕒 当前北京时间：{run_context['current_bj_datetime']}")
    print(f"🧭 当前报告模式：{report_profile['label']}")
    recent_links = load_recent_post_links(
        run_context["current_bj_date"],
        report_profile,
    )
    if recent_links:
        print(f"🧹 已读取最近同类文章链接 {len(recent_links)} 条，用于过滤重复候选。")

    print("🚀 正在抓取印尼新闻源...")
    news_data = fetch_indonesia_news(
        report_profile["rss_sources"],
        run_context["current_bj_date"],
        exclude_links=recent_links,
    )
    print(f"✅ 已整理 {len(news_data)} 条候选新闻。")
    recent_headlines = load_recent_post_headlines(
        run_context["current_bj_date"],
        report_profile,
    )
    if recent_headlines:
        print(f"🧹 已读取最近同类文章标题 {len(recent_headlines)} 条，用于降低重复选题。")

    if fetch_only:
        print("\n以下为抓取结果预览：")
        for index, item in enumerate(news_data, start=1):
            print(f"{index}. [{item['source']}] {item['title']}")
            print(f"   {item['link']}")

        return {
            "status": "ok",
            "mode": report_profile["kind"],
            "label": report_profile["label"],
            "date": run_context["current_bj_date"],
            "fetched_count": len(news_data),
            "fetch_only": True,
        }

    try:
        content = process_news_with_ai(
            news_data,
            report_profile["system_prompt"],
            run_context["current_bj_date"],
            recent_headlines,
            report_profile.get("required_item_count"),
        )
    except RuntimeError as exc:
        raw_output_path = save_raw_news_to_markdown(news_data, run_context)
        print(f"❌ AI 处理失败：{exc}")
        print(f"📝 已先保存候选新闻原始列表：{raw_output_path}")
        raise

    output_path = save_to_markdown(content, report_profile, run_context, news_data)
    print(f"✅ 简报已生成：{output_path}")

    github_result = push_to_github(output_path)
    if github_result.get("enabled"):
        print(f"✅ GitHub 推送结果：{github_result['status']}")

    wechat_result = publish_to_wechat(output_path)
    if wechat_result.get("enabled"):
        print(f"✅ 微信推送结果：{wechat_result.get('status', 'done')}")

    return {
        "status": "ok",
        "mode": report_profile["kind"],
        "label": report_profile["label"],
        "date": run_context["current_bj_date"],
        "generated_file": str(output_path),
        "fetched_count": len(news_data),
        "github": github_result,
        "wechat": wechat_result,
    }


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

    try:
        run_daily_job(fetch_only=args.fetch_only)
    except RuntimeError as exc:
        print(f"❌ 任务执行失败：{exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
