#!/bin/bash
# build.sh — Render 部署時自動下載 Fairy-Stockfish Linux 二進制

set -e

pip install -r requirements.txt

# 下載 Fairy-Stockfish Linux x86-64 執行檔
FSFISH_URL="https://github.com/fairy-stockfish/Fairy-Stockfish/releases/download/fairy-sf-14/fairy-stockfish-largeboard_x86-64"
echo "[build] 下載 Fairy-Stockfish..."
curl -L "$FSFISH_URL" -o fairy-stockfish
chmod +x fairy-stockfish

echo "[build] 驗證引擎..."
echo "uci" | timeout 5 ./fairy-stockfish | head -5 || echo "[build] 警告：引擎驗證失敗，繼續部署"

echo "[build] 完成！"
