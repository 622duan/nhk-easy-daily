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
from typing import List, Dict, Any

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


def article_to_news_dict(article: Dict[str, Any], level: str = "N3") -> Dict[str, Any]:
    """单篇 NHKArticle → app newsList 元素"""
    body_html = article.get("body_html", "")
    body_paragraphs = split_body_paragraphs(body_html) or [article.get("body", "")]
    words = ruby_to_word_dicts(body_html)

    # 估算词数 (含汉字 ruby 标注的所有词)
    word_count = len(words) if words else article.get("word_count", 0)

    # 英文版 URL: NHK World 同一篇文章
    # /news/easy/XXX/XXX.html → /news/XXX.html
    news_id = article.get("news_id", "")
    en_url = f"https://www3.nhk.or.jp/news/{news_id}.html" if news_id else article.get("url", "")

    return {
        "id": f"nhk-{news_id}",
        "badge": level,
        "date": format_date_jp(article.get("published_at", "")),
        "title_jp": article.get("title_with_ruby", article.get("title", "")),
        "title_zh": "",  # 留空, UI 端处理
        "duration": estimate_duration(word_count),
        "plays": "new",
        "thumb": article.get("image_url", "") or "https://images.unsplash.com/photo-1495020689067-958852a7765e?auto=format&fit=crop&w=400&q=80",
        "externalUrl": en_url,
        "audioUrl": article.get("audio_url", ""),
        "body": body_paragraphs,
        "words": words[:20],  # 限制每篇最多 20 个生词, 避免 UI 太长
        "source": "NHK Easy News",
    }


def main():
    parser = argparse.ArgumentParser(description="NHK 抓取数据 → app 格式")
    parser.add_argument("--input", "-i", default="data/nhk-today.json", help="fetch_nhk.py 输出")
    parser.add_argument("--output", "-o", default="data/nhk-app-format.json", help="app 格式输出")
    parser.add_argument("--level", default="N3", help="默认 level (默认 N3, NHK Easy News 难度)")
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"ERROR: 输入文件不存在: {in_path}", file=sys.stderr)
        sys.exit(1)

    with open(in_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    articles = data.get("articles", [])
    news_items = [article_to_news_dict(a, level=args.level) for a in articles]

    output = {
        "version": datetime.now(JST).strftime("%Y-%m-%d"),
        "source": data.get("source", "https://www3.nhk.or.jp/news/easy/"),
        "fetched_at": data.get("fetched_at", ""),
        "default_level": args.level,
        "items": news_items,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✓ 转换 {len(news_items)} 篇 → {out_path}", file=sys.stderr)
    for item in news_items:
        print(f"  - {item['id']}: {item['title_jp'][:50]}... ({len(item['words'])} 词)", file=sys.stderr)


if __name__ == "__main__":
    main()
