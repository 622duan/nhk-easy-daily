#!/usr/bin/env python3
"""
NHK Easy News 抓取器
====================

每天从 https://www3.nhk.or.jp/news/easy/ 抓当日文章, 输出为结构化 JSON.

NHK Easy News 页面结构 (基于公开 HTML 抓取经验):
  - 主页列出当日 3-5 篇文章, 每篇链接形如:
    https://www3.nhk.or.jp/news/easy/<NEWS_ID>/<NEWS_ID>.html
  - 文章页关键元素:
    <h1 class="article-title">       主标题 (可能含 <ruby>)
    <div id="js-article-body">       正文 (paragraphs, 每段含 ruby 标注)
    <span class="word">              单词 (带 ruby 振假名)
    <a class="audio-src" data-url>   音频 URL
    <time datetime="...">            发布时间
    <p id="js-outline">              简介 (一段)
"""

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup, Tag
except ImportError:
    print("ERROR: 需要安装 requests 和 beautifulsoup4", file=sys.stderr)
    print("  pip install requests beautifulsoup4 lxml", file=sys.stderr)
    sys.exit(1)


# ---- 常量 ----
NHK_EASY_BASE = "https://www3.nhk.or.jp/news/easy/"
NHK_EASY_BASES = [
    "https://news.web.nhk/news/easy/",  # 新域名 (Next.js 渲染, 主页 JS 加载)
    "https://www3.nhk.or.jp/news/easy/",  # 老域名
]
# NHK Easy News 的 sitemap (新版用 article/{slug} 或 ne{YYYYMMDDHHMMSS} 模式)
NHK_EASY_SITEMAP = "https://news.web.nhk/news/easy/sitemap/sitemap.xml"
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

JST = timezone(timedelta(hours=9))


# ---- 数据结构 ----
@dataclass
class NHKArticle:
    """单篇 NHK Easy News 文章"""
    news_id: str
    title: str                       # 纯文本
    title_with_ruby: str             # 带 <ruby> 标签的 HTML
    body: str                        # 纯文本 (按段分, 数组字符串)
    body_html: str                   # 带 ruby 的 HTML
    outline: str                     # 简介
    audio_url: Optional[str]
    image_url: Optional[str]
    url: str
    published_at: str                # ISO 8601 (JST)
    word_count: int = 0              # body 中 ruby 标注的单词数
    fetched_at: str = ""             # 抓取时间 (JST)


# ---- 抓取函数 ----
def fetch_html(url: str, timeout: int = 30) -> str:
    """抓取 URL 返回 HTML 文本"""
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    # NHK 页面通常是 UTF-8
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def fetch_index_html(timeout: int = 30) -> str:
    """抓取 NHK Easy News 主页 - 尝试多个域名 (NHK 改过域名)"""
    last_error = None
    for base in NHK_EASY_BASES:
        try:
            print(f"  [try] {base}", file=sys.stderr)
            html = fetch_html(base, timeout=timeout)
            # 抓一下页面的真实 URL (follow redirect 后)
            print(f"  [ok] {len(html)} bytes", file=sys.stderr)
            return html
        except Exception as e:
            last_error = e
            print(f"  [fail] {base}: {e}", file=sys.stderr)
    raise last_error or Exception("All NHK bases failed")


def extract_article_links_from_sitemap(sitemap_url: str = NHK_EASY_SITEMAP) -> List[Dict[str, str]]:
    """从 NHK Easy News sitemap 提取所有文章链接 + 解析 news_id 日期

    Returns:
        List of {url, news_id, lastmod, date}
    """
    try:
        xml_text = fetch_html(sitemap_url)
    except Exception as e:
        print(f"SITEMAP_FETCH_ERROR: {e}", file=sys.stderr)
        return []

    # 解析 XML
    soup = BeautifulSoup(xml_text, "xml")
    articles = []

    for url_elem in soup.find_all("url"):
        loc = url_elem.find("loc")
        lastmod = url_elem.find("lastmod")
        if not loc:
            continue
        loc_text = loc.get_text(strip=True)
        lastmod_text = lastmod.get_text(strip=True) if lastmod else ""

        # 只取 ne{YYYYMMDDHHMMSS} 模式的最新 daily news
        if "/news/easy/ne" in loc_text and loc_text.endswith(".html"):
            m = re.search(r"/news/easy/(ne(\d{8})\d+)/", loc_text)
            if m:
                news_id = m.group(1)
                date_str = m.group(2)  # YYYYMMDD
                # 转成 YYYY-MM-DD
                date_iso = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
                articles.append({
                    "url": loc_text,
                    "news_id": news_id,
                    "lastmod": lastmod_text,
                    "date": date_iso,
                })
        # 老的 article/{slug} 模式 (disaster/typhoon 等静态页, 跳过)
        # 暂不取, 因为它们是话题页不是 daily news

    # 按 news_id 倒序 (最新的在前)
    articles.sort(key=lambda a: a.get("news_id", ""), reverse=True)
    return articles


def extract_article_links(index_html: str) -> List[str]:
    """从 NHK Easy News 主页提取所有文章链接 (老方法, 已废弃)"""
    soup = BeautifulSoup(index_html, "lxml")
    soup_text = str(soup)  # for debug
    links = set()
    # 注: verbose 不在参数里, 总是打印 debug 提示
    verbose = True

    for a in soup.find_all("a", href=True):
        href = a["href"]
        # 匹配形如 /news/easy/XXXX/XXXX.html 或 https://www3.nhk.or.jp/news/easy/XXXX/XXXX.html
        # 也兼容 news.web.nhk 域名
        m = re.search(r"/news/easy/([a-z0-9\-_]+)/([a-z0-9\-_]+)\.html$", href)
        if m:
            # 用 href 的域名作为 base
            if "news.web.nhk" in href:
                full_url = href if href.startswith("http") else urljoin("https://news.web.nhk/", href)
            else:
                full_url = href if href.startswith("http") else urljoin(NHK_EASY_BASE, href)
            links.add(full_url)

    # 调试: 打印找到的 /news/easy/ 链接
    if verbose and not links:
        all_easy = re.findall(r"href=['\"]([^'\"]*news/easy[^'\"]*)['\"]", soup_text)
        print(f"  [debug] 找到 {len(all_easy)} 个含 'news/easy' 的链接 (但都不匹配严格格式):", file=sys.stderr)
        for h in all_easy[:5]:
            print(f"    - {h}", file=sys.stderr)

    return sorted(links)


def extract_text_with_ruby(elem) -> str:
    """提取元素文本, 保留 ruby 标注的 HTML"""
    parts = []
    for child in elem.descendants:
        if isinstance(child, Tag):
            if child.name == "rt":
                continue  # rt 内容由 ruby 标签包裹
            if child.name == "ruby":
                # 已经在 parts 里了, 跳过
                continue
        if isinstance(child, str):
            txt = child.strip()
            if txt:
                parts.append(txt)
    # 用 soup 的 str() 保留 ruby 标签
    return str(elem)


def extract_plain_text(elem) -> str:
    """提取纯文本, 移除 ruby 但保留汉字+振假名合并形式"""
    # 提取所有文本节点, 用空格连接
    texts = []
    for s in elem.stripped_strings:
        texts.append(s)
    return " ".join(texts)


def parse_article(html: str, url: str, verbose: bool = True) -> Optional[NHKArticle]:
    """解析单篇 NHK Easy News 文章"""
    soup = BeautifulSoup(html, "lxml")

    def debug(msg):
        if verbose:
            print(f"    [parse] {msg}", file=sys.stderr)

    # ---- 提取 news_id ----
    m = re.search(r"/news/easy/([a-z0-9\-_]+)/", url)
    if not m:
        debug(f"news_id regex failed for {url}")
        return None
    news_id = m.group(1)

    # ---- 提取标题 ----
    title_elem = (
        soup.find("h1", class_="article-title")
        or soup.find("h1")
        or soup.find("title")
    )
    if not title_elem:
        debug(f"no h1/title found, html length={len(html)}")
        return None
    title_plain = extract_plain_text(title_elem)
    title_with_ruby = str(title_elem)

    if not title_plain or len(title_plain.strip()) < 3:
        debug(f"title too short: {title_plain!r}")
        return None

    # ---- 提取简介 ----
    outline = ""
    outline_elem = soup.find(id="js-outline") or soup.find(class_="article-outline")
    if outline_elem:
        outline = extract_plain_text(outline_elem)

    # ---- 提取正文 ----
    body_elem = (
        soup.find(id="js-article-body")
        or soup.find(class_="article-body")
        or soup.find(class_="article-body__content")
        or soup.find("article")
    )
    if not body_elem:
        # 兜底: 找所有的 <p> 标签
        all_p = soup.find_all("p")
        if all_p:
            debug(f"no body_elem, using all <p> ({len(all_p)} found)")
            paragraphs = []
            for p in all_p:
                txt = extract_plain_text(p)
                if txt and len(txt) > 20:  # 过滤短段 (如版权声明)
                    paragraphs.append(txt)
            body_plain = "\n".join(paragraphs)
            body_html = "\n".join(str(p) for p in all_p)
        else:
            debug(f"no body_elem, no <p> found")
            return None
    else:
        # 按段切分
        paragraphs = []
        for p in body_elem.find_all("p"):
            txt = extract_plain_text(p)
            if txt:
                paragraphs.append(txt)
        body_plain = "\n".join(paragraphs)
        body_html = str(body_elem)

    if not body_plain or len(body_plain) < 30:
        debug(f"body too short: {body_plain[:50]!r}")
        return None

    # ---- 提取音频 URL ----
    audio_url = None
    audio_elem = soup.find(attrs={"data-url": True, "class": re.compile("audio", re.I)})
    if audio_elem:
        audio_url = audio_elem.get("data-url")
    if not audio_url:
        # 兜底: 找 m3u8 链接
        m3u8 = soup.find("a", href=re.compile(r"\.m3u8$"))
        if m3u8:
            audio_url = m3u8.get("href")

    # ---- 提取图片 URL ----
    image_url = None
    img = soup.find("img", class_="article-image") or soup.find("article-img")
    if img and img.get("src"):
        image_url = urljoin(url, img["src"])

    # ---- 发布时间 ----
    published_at = ""
    time_elem = soup.find("time")
    if time_elem and time_elem.get("datetime"):
        published_at = time_elem["datetime"]

    # ---- 统计单词数 (ruby 标注) ----
    word_count = len(soup.find_all("ruby"))

    debug(f"OK: {title_plain[:30]}... body={len(body_plain)}字 words={word_count}")

    return NHKArticle(
        news_id=news_id,
        title=title_plain,
        title_with_ruby=title_with_ruby,
        body=body_plain,
        body_html=body_html,
        outline=outline,
        audio_url=audio_url,
        image_url=image_url,
        url=url,
        published_at=published_at,
        word_count=word_count,
        fetched_at=datetime.now(JST).isoformat(),
    )


def fetch_daily_articles(
    limit: int = 5,
    delay: float = 1.0,
    verbose: bool = True,
) -> List[NHKArticle]:
    """
    抓取 NHK Easy News 当日所有文章.
    用 sitemap 拿当日文章链接 (新 NHK 用 Next.js, 主页 JS 渲染, 抓不到).

    Returns:
        List[NHKArticle] - 按发布时间倒序
    """
    if verbose:
        print(f"[{datetime.now(JST).isoformat()}] 抓取 NHK Easy News sitemap...", file=sys.stderr)

    # 用 sitemap 找今天的文章
    sitemap_articles = extract_article_links_from_sitemap()

    if verbose:
        print(f"  → sitemap 找到 {len(sitemap_articles)} 个 ne 文章 URL", file=sys.stderr)

    # 取今天 + 昨天的文章 (NHK 8/5 11:54 抓的, 8/5 还没出, 用 8/4 兜底)
    today = datetime.now(JST)
    today_str = today.strftime("%Y-%m-%d")
    yesterday_str = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    two_days_ago_str = (today - timedelta(days=2)).strftime("%Y-%m-%d")

    # 优先取今天, 没有就拿昨天, 再没有就前天
    todays = [a for a in sitemap_articles if a.get("date") == today_str]
    if not todays:
        if verbose:
            print(f"  → 今日 ({today_str}) 无文章, 改用昨日 ({yesterday_str})", file=sys.stderr)
        todays = [a for a in sitemap_articles if a.get("date") == yesterday_str]
    if not todays:
        if verbose:
            print(f"  → 昨日也无, 改用前日 ({two_days_ago_str})", file=sys.stderr)
        todays = [a for a in sitemap_articles if a.get("date") == two_days_ago_str]

    if verbose:
        print(f"  → 找到 {len(todays)} 篇文章 (目标日期范围: today/yesterday/2-days-ago)", file=sys.stderr)
        for a in todays[:5]:
            print(f"    - {a['news_id']} ({a['date']}) {a['url'][:80]}", file=sys.stderr)

    if limit > 0:
        todays = todays[:limit]

    articles = []
    for i, item in enumerate(todays, 1):
        link = item["url"]
        if verbose:
            print(f"  [{i}/{len(todays)}] {link}", file=sys.stderr)
        try:
            html = fetch_html(link)
            article = parse_article(html, link)
            if article:
                articles.append(article)
                if verbose:
                    print(f"    ✓ {article.title[:40]}... ({article.word_count} 单词)", file=sys.stderr)
        except Exception as e:
            print(f"    ✗ 抓取失败: {e}", file=sys.stderr)
        time.sleep(delay)

    return articles


def load_yesterday() -> List[NHKArticle]:
    """如果 NHK 抓不到, 用前一天的数据 (data/yesterday.json)

    优先级: yesterday.json > (空)
    注: 之前用 fallback.json, 现在改用 yesterday.json (前一天 commit 的内容)
    """
    from pathlib import Path
    yesterday_path = Path(__file__).parent.parent / "data" / "yesterday.json"
    if not yesterday_path.exists():
        return []
    try:
        with open(yesterday_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        articles = [NHKArticle(**a) for a in data.get("articles", [])]
        print(f"YESTERDAY_LOADED: {len(articles)} 篇", file=sys.stderr)
        return articles
    except Exception as e:
        print(f"YESTERDAY_LOAD_ERROR: {e}", file=sys.stderr)
        return []

# 兼容旧名字
def load_fallback() -> List[NHKArticle]:
    """deprecated: 用 load_yesterday() 替代"""
    return load_yesterday()


# ---- 入口 ----
def main():
    parser = argparse.ArgumentParser(description="NHK Easy News 抓取器")
    parser.add_argument("--limit", type=int, default=5, help="最多抓取几篇 (默认 5)")
    parser.add_argument("--delay", type=float, default=1.0, help="文章间延迟秒数 (默认 1.0)")
    parser.add_argument("--output", "-o", default="data/nhk-today.json", help="输出 JSON 路径")
    parser.add_argument("--quiet", action="store_true", help="静默模式")
    parser.add_argument("--no-fallback", action="store_true", help="禁用 fallback (抓空时失败)")
    args = parser.parse_args()

    articles = []
    fetch_error = None
    try:
        articles = fetch_daily_articles(
            limit=args.limit,
            delay=args.delay,
            verbose=not args.quiet,
        )
    except Exception as e:
        fetch_error = str(e)
        print(f"FETCH_ERROR: {e}", file=sys.stderr)

    # 抓取为空 (周末/节假日) 时, 用昨天数据兜底
    used_yesterday = False
    if not articles and not args.no_fallback:
        yesterday = load_yesterday()
        if yesterday:
            articles = yesterday
            used_yesterday = True
            if not args.quiet:
                print(f"⚠️  抓取为空, 用昨天数据 ({len(yesterday)} 篇)", file=sys.stderr)

    if not articles and not args.no_fallback:
        # 既没抓到, 也没 fallback → 失败
        print("FATAL: 没抓到任何文章, 也无 fallback", file=sys.stderr)
        sys.exit(1)

    output = {
        "fetched_at": datetime.now(JST).isoformat(),
        "source": NHK_EASY_BASE,
        "article_count": len(articles),
        "used_yesterday": used_yesterday,
        "fetch_error": fetch_error,
        "articles": [asdict(a) for a in articles],
    }

    import os
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    if not args.quiet:
        print(f"\n✓ 共抓取 {len(articles)} 篇文章, 已写入 {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
