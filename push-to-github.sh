#!/bin/bash
# 一键初始化 + 推送到 GitHub
# 用法: ./push-to-github.sh git@github.com:YOUR_USERNAME/nhk-easy-daily.git

set -e

if [ -z "$1" ]; then
  echo "用法: $0 <git-url>"
  echo "  例如: $0 git@github.com:octocat/nhk-easy-daily.git"
  exit 1
fi

REPO_URL="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"

echo "→ 初始化 git..."
if [ ! -d .git ]; then
  git init
  git branch -M main
else
  echo "  (已经初始化过, 跳过)"
fi

echo "→ 添加远程..."
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO_URL"

echo "→ 添加文件..."
git add .

echo "→ 检查状态..."
git status --short

echo ""
echo "→ 提交..."
git commit -m "init: NHK Easy News daily fetcher pipeline" || echo "  (无新变更, 跳过)"

echo ""
echo "→ 推送到 $REPO_URL ..."
git push -u origin main

echo ""
echo "✓ 完成!"
echo ""
echo "下一步:"
echo "  1. 打开 https://github.com/${REPO_URL##*:} → Actions 标签"
echo "  2. 启用 workflows"
echo "  3. 点 'Daily NHK Easy News' → 'Run workflow' 测试"
