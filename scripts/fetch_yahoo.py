#!/usr/bin/env python3
"""
Yahoo News Japan 抓取器
=======================

从 Yahoo News Japan RSS 抓取最新日语新闻 (普通日语, 比 NHK Easy 长).

Yahoo News Japan RSS: https://news.yahoo.co.jp/rss/topics/top-picks.xml
单文章 pickup 页: https://news.yahoo.co.jp/pickup/{id}?source=rss
单文章 hash URL: https://news.yahoo.co.jp/articles/{hash_id} (完整版)

输出格式: 跟 fetch_nhk.py 兼容, items 含:
- id: yahoo-{article_id}
- title
- body: 多段日文正文 (200-1500 字)
- audio_url: 暂无 (用 TTS 录)
- thumb: 缩略图 URL
- level: 默认 N2 (Yahoo News 是普通日语, 比 NHK Easy 难)
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
    sys.exit(1)


# ---- 常量 ----
JST = timezone(timedelta(hours=9))
YAHOO_RSS = "https://news.yahoo.co.jp/rss/topics/top-picks.xml"
YAHOO_RSS_ALL = "https://news.yahoo.co.jp/rss/topics/world.xml"  # 国际新闻
DEFAULT_HEADERS = {
    # 用 desktop UA: Yahoo 给 mobile UA client-side rendered HTML, desktop UA 给 SSR 含完整内容
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


@dataclass
class YahooArticle:
    article_id: str          # 短 ID (pickup id) 或 hash
    title: str
    body_paragraphs: List[str]  # 完整段
    body: str                # 合并成一段字符串
    source: str              # 读卖, 共同, 时事 等
    url: str
    pickup_url: str
    thumb: str
    published_at: str
    level: str = "N2"        # Yahoo News 难度默认 N2
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def fetch_url(url: str, timeout: int = 15) -> str:
    """带 retry 的 fetch"""
    for attempt in range(3):
        try:
            r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def parse_rss(xml_text: str) -> List[Dict[str, str]]:
    """解析 Yahoo RSS XML, 提取 article items"""
    soup = BeautifulSoup(xml_text, "xml")
    items = []
    for item in soup.find_all("item"):
        title = item.find("title")
        link = item.find("link")
        pubdate = item.find("pubDate")
        description = item.find("description")
        if not title or not link:
            continue
        items.append({
            "title": title.get_text(strip=True),
            "link": link.get_text(strip=True),
            "pubdate": pubdate.get_text(strip=True) if pubdate else "",
            "description": description.get_text(strip=True) if description else "",
        })
    return items


def extract_article_hash(pickup_url: str) -> Optional[str]:
    """从 pickup 页提取完整版 articles/{hash} 链接 + meta description (摘要, 抓不到完整 body 时的 fallback)"""
    try:
        html = fetch_url(pickup_url, timeout=12)
        soup = BeautifulSoup(html, "lxml")
        hash_id, hash_url = None, None
        desc = ""

        # 找 hash URL
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "news.yahoo.co.jp/articles/" in href:
                m = re.search(r"articles/([a-f0-9]+)", href)
                if m:
                    hash_id = m.group(1)
                    hash_url = href
                    break

        # 找 meta description 作为 body fallback
        # Yahoo pickup 页 description 通常 150-300 字
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            desc = meta_desc.get("content", "").strip()
        if not desc:
            og_desc = soup.find("meta", attrs={"property": "og:description"})
            if og_desc and og_desc.get("content"):
                desc = og_desc.get("content", "").strip()

        return hash_id, hash_url, desc
    except Exception as e:
        print(f"  [extract_hash] {e}", file=sys.stderr)
    return None, None, ""


def parse_article(html: str, url: str) -> YahooArticle:
    """解析单篇 Yahoo News 文章完整版"""
    soup = BeautifulSoup(html, "lxml")
    
    # 标题
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    
    # 文章 ID
    m = re.search(r"articles/([a-f0-9]+)", url)
    article_id = m.group(1) if m else ""
    
    # 正文段: Yahoo 用 sc-54nboa-0 zUIkh class
    body_paragraphs = []
    for p in soup.find_all("p", class_=re.compile(r"sc-54nboa-0")):
        text = p.get_text(strip=True)
        # 过滤短段 + 表单提示
        if len(text) < 20:
            continue
        if any(skip in text for skip in ["みんなの意見", "コメント", "関連ニュース", "写真"]):
            continue
        body_paragraphs.append(text)
    
    # 来源
    source = ""
    # 读卖 / 共同 / 时事 标识
    for elem in soup.find_all(["span", "a", "div"]):
        text = elem.get_text(strip=True)
        for src in ["読売新聞", "共同通信", "時事通信", "毎日新聞", "朝日新聞", "産経新聞", "日本経済新聞", "NHK", "FNN", "TBS", "ANN"]:
            if src in text and len(text) < 30:
                source = src
                break
        if source:
            break
    
    # 缩略图
    thumb = ""
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if "news-pctr.c.yimg.jp" in src and ("_view" in src or "/t/" in src):
            thumb = src
            break
    if not thumb:
        og = soup.find("meta", property="og:image")
        if og:
            thumb = og.get("content", "")
    
    # 发布时间 (从 URL pubDate 或页面)
    pub = ""
    time_elem = soup.find("time")
    if time_elem:
        pub = time_elem.get_text(strip=True)
    
    return YahooArticle(
        article_id=article_id,
        title=title,
        body_paragraphs=body_paragraphs,
        body="\n\n".join(body_paragraphs),
        source=source or "Yahoo News",
        url=url,
        pickup_url="",
        thumb=thumb,
        published_at=pub,
    )


def estimate_level(article: YahooArticle) -> str:
    """估算难度等级 (基于 body 长度和字符)"""
    body = article.body
    if not body:
        return "N2"
    # 估算平均句长
    sentences = re.split(r"[。！？]", body)
    sentences = [s for s in sentences if len(s) > 5]
    if not sentences:
        return "N2"
    avg_len = sum(len(s) for s in sentences) / len(sentences)
    # N3: 短句多 (avg<25), N2: 中等 (25-40), N1: 长句多 (>40)
    if avg_len < 25:
        return "N3"
    elif avg_len < 40:
        return "N2"
    else:
        return "N1"


def fetch_daily_articles(limit: int = 5, verbose: bool = True) -> List[YahooArticle]:
    """抓取 Yahoo News Japan 当日头条"""
    if verbose:
        print(f"[{datetime.now(JST).isoformat()}] 抓取 Yahoo News RSS...", file=sys.stderr)
    
    articles = []
    
    # 1. 抓 RSS
    rss_items = []
    for rss_url in [YAHOO_RSS]:
        try:
            xml = fetch_url(rss_url, timeout=12)
            rss_items.extend(parse_rss(xml))
            if verbose:
                print(f"  → RSS {rss_url}: {len(rss_items)} items", file=sys.stderr)
        except Exception as e:
            print(f"  [rss err] {rss_url}: {e}", file=sys.stderr)
    
    if not rss_items:
        return articles
    
    # 2. 每条 article 抓摘要 (Yahoo 文章正文是 JS 渲染, 用 meta description 150-300 字)
    for item in rss_items[:limit]:
        if verbose:
            print(f"  → 抓: {item['title'][:50]}", file=sys.stderr)

        pickup_url = item["link"]
        # 从 pickup URL 提取 ID
        m = re.search(r"pickup/(\d+)", pickup_url)
        pickup_id = m.group(1) if m else item["title"][:20]

        try:
            # 抓 pickup 页 (拿 description 摘要)
            html = fetch_url(pickup_url, timeout=12)
            soup = BeautifulSoup(html, "lxml")

            article = YahooArticle(
                article_id=pickup_id,
                title=item["title"],
                body_paragraphs=[],
                body="",
                source="",
                url=pickup_url,
                pickup_url=pickup_url,
                thumb="",
                published_at=item.get("pubdate", ""),
            )

            # 拿 description (150-300 字摘要)
            desc = ""
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                desc = meta_desc.get("content", "").strip()
            if not desc:
                og_desc = soup.find("meta", attrs={"property": "og:description"})
                if og_desc and og_desc.get("content"):
                    desc = og_desc.get("content", "").strip()

            # RSS description 也作为 fallback
            if not desc and item.get("description"):
                desc = item["description"].strip()

            article.body = desc
            if desc:
                # 切段 (按。切)
                article.body_paragraphs = [p.strip() for p in re.split(r"[。！？]", desc) if p.strip() and len(p.strip()) > 10]

            # 来源
            source = ""
            for src in ["読売新聞", "共同通信", "時事通信", "毎日新聞", "朝日新聞", "産経新聞", "日本経済新聞", "NHK", "FNN", "TBS", "ANN", "北海道新聞", "中日新聞", "西日本新聞"]:
                if src in desc or src in html[:5000]:
                    source = src
                    break
            article.source = source

            # 缩略图
            og = soup.find("meta", attrs={"property": "og:image"})
            if og and og.get("content"):
                article.thumb = og.get("content", "")

            # 估算 level
            article.level = estimate_level(article)

            if article.body and len(article.body) > 50:
                articles.append(article)
                if verbose:
                    print(f"    OK: body={len(article.body)}字 level={article.level} source={article.source}", file=sys.stderr)
            else:
                if verbose:
                    print(f"    SKIP: body 太短 ({len(article.body)}字)", file=sys.stderr)
        except Exception as e:
            if verbose:
                print(f"    [err] {e}", file=sys.stderr)
            continue
    
    return articles


def main():
    parser = argparse.ArgumentParser(description="Yahoo News Japan 抓取器")
    parser.add_argument("--limit", type=int, default=5, help="抓取篇数")
    parser.add_argument("--output", "-o", default="data/yahoo-today.json", help="输出文件")
    parser.add_argument("--quiet", action="store_true", help="静默")
    
    args = parser.parse_args()
    verbose = not args.quiet
    
    articles = fetch_daily_articles(limit=args.limit, verbose=verbose)
    
    output = {
        "fetched_at": datetime.now(JST).isoformat(),
        "source": "Yahoo News Japan",
        "article_count": len(articles),
        "items": [a.to_dict() for a in articles],
    }
    
    import os
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    if verbose:
        print(f"OK: {len(articles)} 篇 -> {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
