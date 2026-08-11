#!/usr/bin/env python3
"""
NHK Easy News → App 数据格式转换器
====================================

将 fetch_nhk.py 抓取的 NHKArticle 转成 app data.js 中 newsList 元素的格式.

输出 Schema (与 /workspace/prototype/data.js 中 N5.newsList 元素完全一致):
  {
    id: "nhk-{news_id}",
    badge: "N3",                # NHK Easy News 默认 N3 难度
    date: "8月3日",             # 中文日期格式
    title_jp: "<ruby>...</ruby>",
    title_zh: "",               # 留空, UI 会显示"查看英文版"
    duration: "3:45",           # 估算: 单词数 * 0.5 秒
    plays: "new",               # 标记为新发布
    thumb: "https://...",       # NHK 配图
    externalUrl: "https://...", # 跳转 NHK 英文版
    body: ["<ruby>...</ruby>", ...],
    words: [{ word, kana, meaning, pos }, ...]
  }

Words 提取规则:
  - 从 body 中 <ruby>漢字<rt>かんじ</rt></ruby> 提取
  - meaning 留空 (UI 端用 hover/click 调 API 或显示空)
  - pos 留空
  - 重复词去重, 保留第一次出现位置
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

JST = timezone(timedelta(hours=9))


def ruby_to_word_dicts(html: str) -> List[Dict[str, str]]:
    """
    从含 <ruby> 的 HTML 提取 word 列表.
    形如 <ruby>東京<rt>とうきょう</rt></ruby> → {word:'東京', kana:'とうきょう'}
    """
    seen = set()
    words = []
    # 匹配 <ruby>(内容)<rt>(振假名)</rt></ruby>, 内容里可能嵌套 ruby
    # 用非贪婪 + dotall, 防止跨段匹配
    pattern = re.compile(r"<ruby>(.+?)<rt>([^<]+)</rt></ruby>", re.DOTALL)
    for m in pattern.finditer(html):
        base = m.group(1).strip()
        ruby = m.group(2).strip()
        # 去除 base 里嵌套的 ruby 标签
        base = re.sub(r"<rt>[^<]*</rt>", "", base)
        base = re.sub(r"</?ruby>", "", base)
        base = base.strip()

        key = base + "|" + ruby
        if key in seen or not base:
            continue
        seen.add(key)

        words.append({
            "word": base,
            "kana": ruby,
            "meaning": "",       # 留空
            "pos": "",           # 留空
        })
    return words


def split_body_paragraphs(body_html: str) -> List[str]:
    """
    按 </p> 切分正文, 保留每段里的 ruby 标签.
    """
    # 简单方式: 按 </p> 切, 保留每段完整 HTML
    parts = re.split(r"</p\s*>", body_html, flags=re.IGNORECASE)
    paragraphs = []
    for p in parts:
        # 去掉开头的 <p ...>
        p = re.sub(r"^<p[^>]*>", "", p.strip(), flags=re.IGNORECASE)
        p = p.strip()
        if not p:
            continue
        # 去掉尾部可能残留的 <p 起始
        p = re.sub(r"^\s*<p[^>]*>", "", p)
        # 简单净化: 移除多余空白
        p = re.sub(r"\s+", " ", p)
        if p:
            paragraphs.append(p)
    return paragraphs


def estimate_duration(word_count: int) -> str:
    """根据单词数估算阅读时长, m:ss 格式"""
    # 日语新闻: 约 200 词/分钟 (NHK 慢速)
    # 单词+汉字混排, 大概 150 词/分钟
    seconds = max(60, int(word_count * 0.4))
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def format_date_jp(iso_date: str) -> str:
    """从 ISO 8601 (JST) 转 '8月3日' 格式"""
    if not iso_date:
        return ""
    try:
        # 处理 '2026-08-03T09:00:00+09:00' 或 '2026-08-03T00:00:00Z'
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        return f"{dt.month}月{dt.day}日"
    except Exception:
        return ""


def article_to_news_dict(article: Dict[str, Any], level: Optional[str] = None) -> Dict[str, Any]:
    """单篇 NHKArticle → app newsList 元素 (适配新版 NHK 无 ruby 格式)

    level: 不传则用 article 自带的 level 字段 (按字数估算 N4/N3/N2)
    """
    body_html = article.get("body_html", "")
    body_plain = article.get("body", "")

    # 优先用 article 自带的 level (按字数估算), fallback 到参数
    if level is None:
        level = article.get("level", "N3")

    # 切分段: 优先用 body_html 的 <p> 切, 失败用 body plain
    body_paragraphs = split_body_paragraphs(body_html)
    if not body_paragraphs and body_plain:
        # 用 plain text 按 \n 切段
        body_paragraphs = [p.strip() for p in body_plain.split("\n") if p.strip()]

    # 去 HTML 标签: 新版 body_html 是含 <p> 的 HTML, body_paragraphs 已经去 tag
    # 如果没有切好, body_paragraphs 可能是 <p>...</p> 完整 HTML, 需要去 tag
    clean_paragraphs = []
    for p in body_paragraphs:
        # 去 <p> 等标签
        p_clean = re.sub(r"<[^>]+>", "", p).strip()
        p_clean = re.sub(r"\s+", " ", p_clean)
        if p_clean:
            clean_paragraphs.append(p_clean)

    # ruby words (新版没有 ruby, 通常 0 个)
    words = ruby_to_word_dicts(body_html)

    # 估算词数
    word_count = len(words) if words else article.get("word_count", 0)

    # 英文版 URL
    news_id = article.get("news_id", "")
    en_url = f"https://www3.nhk.or.jp/news/{news_id}.html" if news_id else article.get("url", "")

    # title: 用 plain text, 不用 title_with_ruby (新版有 h1 class style)
    title_plain = article.get("title", "")

    return {
        "id": f"nhk-{news_id}",
        "badge": level,
        "date": format_date_jp(article.get("published_at", "")),
        "title_jp": title_plain,  # 用 plain title
        "title_zh": "",  # 留空, UI 端处理
        "duration": estimate_duration(word_count),
        "plays": "new",
        "thumb": article.get("image_url", "") or "https://images.unsplash.com/photo-1495020689067-958852a7765e?auto=format&fit=crop&w=400&q=80",
        "externalUrl": en_url,
        # audioUrl 优先级: fetch_nhk.py 抓的 audio_url > 本地 data/audio/{news_id}.mp3 (TTS录)
        # news_id 可能是 ne20260805xxxxx (新文章, 已录 TTS) 或 k100xxxx (老文章, NHK 公开 mp3)
        "audioUrl": article.get("audio_url") or f"https://cdn.jsdelivr.net/gh/622duan/nhk-easy-daily@main/data/audio/nhk-{news_id}.mp3",
        "body": clean_paragraphs,
        "words": words[:20],
        "source": "NHK Easy News",
    }


def yahoo_to_news_dict(item: Dict[str, Any]) -> Dict[str, Any]:
    """Yahoo News Japan item → app newsList 元素"""
    pickup_id = item.get("article_id", "")
    title = item.get("title", "")
    body = item.get("body", "")
    source = item.get("source", "Yahoo News")
    pickup_url = item.get("pickup_url", "")
    url = item.get("url", "") or pickup_url
    thumb = item.get("thumb", "")
    pub = item.get("published_at", "")
    level = item.get("level", "N2")

    # 切段
    paragraphs = [p.strip() + "。" for p in body.split("。") if p.strip()]
    if not paragraphs and body:
        paragraphs = [body]

    # 字数估算 duration
    word_count = len(body)
    if word_count < 100:
        duration = "1:00"
    elif word_count < 200:
        duration = "2:00"
    elif word_count < 400:
        duration = "3:00"
    else:
        duration = "4:00"

    return {
        "id": f"yahoo-{pickup_id}",
        "badge": level,
        "date": pub or datetime.now(JST).strftime("%m月%d日"),
        "title_jp": title,
        "title_zh": "",
        "duration": duration,
        "plays": "new",
        "thumb": thumb or "https://images.unsplash.com/photo-1495020689067-958852a7765e?auto=format&fit=crop&w=400&q=80",
        "externalUrl": url,
        # Yahoo 没公开 mp3, 用 TTS 录 (audioUrl 指向 jsdelivr)
        "audioUrl": f"https://cdn.jsdelivr.net/gh/622duan/nhk-easy-daily@main/data/audio/yahoo-{pickup_id}.mp3",
        "body": paragraphs,
        "words": [],  # Yahoo 摘要没 ruby, 留给 UI 端 reverse-match
        "source": f"Yahoo News · {source}" if source else "Yahoo News",
    }


def main():
    parser = argparse.ArgumentParser(description="NHK + Yahoo 抓取数据 → app 格式")
    parser.add_argument("--input", "-i", default="data/nhk-today.json", help="fetch_nhk.py 输出")
    parser.add_argument("--yahoo-input", default="data/yahoo-today.json", help="fetch_yahoo.py 输出 (可选)")
    parser.add_argument("--output", "-o", default="data/nhk-app-format.json", help="app 格式输出")
    parser.add_argument("--level", default="N3", help="默认 level (默认 N3, NHK Easy News 难度)")
    args = parser.parse_args()

    news_items = []

    # 1. NHK
    in_path = Path(args.input)
    if in_path.exists():
        with open(in_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        articles = data.get("articles", [])
        news_items.extend([article_to_news_dict(a) for a in articles])
        print(f"  NHK: {len(articles)} 篇", file=sys.stderr)
    else:
        print(f"  WARN: NHK 文件不存在 {in_path}", file=sys.stderr)

    # 2. Yahoo News Japan
    if args.yahoo_input:
        yahoo_path = Path(args.yahoo_input)
        if yahoo_path.exists():
            with open(yahoo_path, "r", encoding="utf-8") as f:
                yahoo_data = json.load(f)
            yahoo_items = yahoo_data.get("items", [])
            news_items.extend([yahoo_to_news_dict(it) for it in yahoo_items])
            print(f"  Yahoo: {len(yahoo_items)} 篇", file=sys.stderr)
        else:
            print(f"  WARN: Yahoo 文件不存在 {yahoo_path}", file=sys.stderr)

    # 按 level 分组输出
    by_level = {}
    for item in news_items:
        lv = item.get("badge", "N3")
        by_level.setdefault(lv, []).append(item)

    sources = {}
    for item in news_items:
        s = item.get("source", "unknown")
        sources[s] = sources.get(s, 0) + 1

    output = {
        "version": datetime.now(JST).strftime("%Y-%m-%d"),
        "source": "NHK Easy News + Yahoo News Japan",
        "fetched_at": datetime.now(JST).isoformat(),
        "by_level": {lv: len(items) for lv, items in by_level.items()},
        "default_level": args.level,
        "sources": sources,
        "items": news_items,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✓ 转换 {len(news_items)} 篇 → {out_path}", file=sys.stderr)
    print(f"  sources: {sources}", file=sys.stderr)
    for item in news_items:
        print(f"  - {item['id']} [{item['source']}]: {item['title_jp'][:50]}...", file=sys.stderr)


if __name__ == "__main__":
    main()
