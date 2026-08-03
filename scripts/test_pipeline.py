#!/usr/bin/env python3
"""
端到端测试: 验证 format_data.py 输出符合 app 期望的 schema
"""

import json
import sys
from pathlib import Path


def validate_news_item(item: dict) -> list:
    """校验单条 news 元素, 返回错误列表"""
    errors = []
    required = ["id", "badge", "date", "title_jp", "title_zh", "duration",
                "plays", "thumb", "externalUrl", "body", "words"]
    for k in required:
        if k not in item:
            errors.append(f"missing field: {k}")

    if "body" in item and not isinstance(item["body"], list):
        errors.append(f"body should be list, got {type(item['body'])}")

    if "words" in item and isinstance(item["words"], list):
        for i, w in enumerate(item["words"]):
            if not isinstance(w, dict):
                errors.append(f"words[{i}] not dict")
                continue
            for wk in ["word", "kana", "meaning", "pos"]:
                if wk not in w:
                    errors.append(f"words[{i}].{wk} missing")
            if w.get("kana") and not all(ord(c) < 128 for c in w["kana"] if c.isalpha()):
                pass  # kana 含日文正常
    return errors


def main():
    in_path = Path(__file__).parent.parent / "examples" / "mock_app_format.json"
    if not in_path.exists():
        print(f"ERROR: {in_path} 不存在", file=sys.stderr)
        sys.exit(1)

    with open(in_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("items", [])
    if not items:
        print("ERROR: items 为空", file=sys.stderr)
        sys.exit(1)

    total_errors = 0
    for i, item in enumerate(items):
        errors = validate_news_item(item)
        if errors:
            print(f"✗ items[{i}] ({item.get('id', '?')}): {len(errors)} 错误")
            for e in errors:
                print(f"    - {e}")
            total_errors += len(errors)
        else:
            word_count = len(item.get("words", []))
            body_count = len(item.get("body", []))
            print(f"✓ {item['id']}: {item['badge']} | {item['date']} | {body_count} 段, {word_count} 词 | {item['duration']}")

    print(f"\n{'✓ 全部通过' if total_errors == 0 else f'✗ {total_errors} 个错误'}")
    sys.exit(0 if total_errors == 0 else 1)


if __name__ == "__main__":
    main()
