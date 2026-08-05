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
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    # NHK 页面通常是 UTF-8
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def extract_article_links(index_html: str) -> List[str]:
    """从 NHK Easy News 主页提取所有文章链接"""
    soup = BeautifulSoup(index_html, "lxml")
    links = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        # 匹配形如 /news/easy/XXXX/XXXX.html 的链接
        m = re.match(r"^/news/easy/([a-z0-9\-_]+)/([a-z0-9\-_]+)\.html$", href)
        if m:
            full_url = urljoin(NHK_EASY_BASE, href)
            links.add(full_url)

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


def parse_article(html: str, url: str) -> Optional[NHKArticle]:
    """解析单篇 NHK Easy News 文章"""
    soup = BeautifulSoup(html, "lxml")

    # ---- 提取 news_id ----
    # URL 形如 https://www3.nhk.or.jp/news/easy/k1001234567/k1001234567.html
    m = re.search(r"/news/easy/([a-z0-9\-_]+)/", url)
    if not m:
        return None
    news_id = m.group(1)

    # ---- 提取标题 ----
    title_elem = (
        soup.find("h1", class_="article-title")
        or soup.find("h1")
    )
    if not title_elem:
        return None
    title_plain = extract_plain_text(title_elem)
    title_with_ruby = str(title_elem)

    # ---- 提取简介 ----
    outline = ""
    outline_elem = soup.find(id="js-outline") or soup.find(class_="article-outline")
    if outline_elem:
        outline = extract_plain_text(outline_elem)

    # ---- 提取正文 ----
    body_elem = (
        soup.find(id="js-article-body")
        or soup.find(class_="article-body")
        or soup.find("article")
    )
    if not body_elem:
        return None

    # 按段切分
    paragraphs = []
    for p in body_elem.find_all("p"):
        txt = extract_plain_text(p)
        if txt:
            paragraphs.append(txt)
    body_plain = "\n".join(paragraphs)
    body_html = str(body_elem)

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

    Returns:
        List[NHKArticle] - 按发布时间倒序
    """
    if verbose:
        print(f"[{datetime.now(JST).isoformat()}] 抓取 NHK Easy News 主页...", file=sys.stderr)

    index_html = fetch_html(NHK_EASY_BASE)
    links = extract_article_links(index_html)

    if verbose:
        print(f"  → 找到 {len(links)} 篇文章链接", file=sys.stderr)

    if limit > 0:
        links = links[:limit]

    articles = []
    for i, link in enumerate(links, 1):
        if verbose:
            print(f"  [{i}/{len(links)}] {link}", file=sys.stderr)
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


def load_fallback() -> List[NHKArticle]:
    """如果 NHK 抓不到, 用本地 fallback 文件 (data/fallback.json)"""
    from pathlib import Path
    fallback_path = Path(__file__).parent.parent / "data" / "fallback.json"
    if not fallback_path.exists():
        return []
    try:
        with open(fallback_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [NHKArticle(**a) for a in data.get("articles", [])]
    except Exception as e:
        print(f"FALLBACK_LOAD_ERROR: {e}", file=sys.stderr)
        return []


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

    # 抓取为空 (周末/节假日) 时, 用本地 fallback 兜底
    used_fallback = False
    if not articles and not args.no_fallback:
        fallback = load_fallback()
        if fallback:
            articles = fallback
            used_fallback = True
            if not args.quiet:
                print(f"⚠️  抓取为空, 用 fallback 数据 ({len(fallback)} 篇)", file=sys.stderr)

    if not articles and not args.no_fallback:
        # 既没抓到, 也没 fallback → 失败
        print("FATAL: 没抓到任何文章, 也无 fallback", file=sys.stderr)
        sys.exit(1)

    output = {
        "fetched_at": datetime.now(JST).isoformat(),
        "source": NHK_EASY_BASE,
        "article_count": len(articles),
        "used_fallback": used_fallback,
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
