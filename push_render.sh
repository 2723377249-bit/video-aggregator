#!/usr/bin/env bash
# 用法：在「克隆下来的 GitHub 仓库目录」里运行此脚本
#   bash /path/to/deploy-render/push_render.sh
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
echo "==> 把 deploy-render 内容复制到当前目录（当前: $(pwd)）"
cp -r "$SRC/." . 2>/dev/null || true
git add -A
git commit -m "deploy video aggregator ($(date +%F %T))" || echo "（无新改动，跳过提交）"
git push
echo "✅ 已推送。到 Render Dashboard 连接此仓库并部署即可。"
