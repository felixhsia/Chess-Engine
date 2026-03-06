#!/bin/bash
# build.sh — 從源碼編譯 Fairy-Stockfish
set -e

pip install -r requirements.txt

if [ -f "fairy-stockfish" ]; then
    echo "[build] 引擎已存在，跳過編譯"
    exit 0
fi

echo "[build] 安裝編譯工具..."
apt-get update -qq && apt-get install -y -qq g++ make git

echo "[build] 下載 Fairy-Stockfish 源碼..."
git clone --depth=1 https://github.com/fairy-stockfish/Fairy-Stockfish.git fs_src

echo "[build] 編譯中（約 2-3 分鐘）..."
cd fs_src/src
make -j2 build ARCH=x86-64-modern COMP=gcc largeboards=yes 2>&1 | tail -10

echo "[build] 尋找編譯結果..."
find . -name "stockfish*" -o -name "fairy*" 2>/dev/null | head -10

# 編譯結果可能叫 stockfish 或 fairy-stockfish
if [ -f "stockfish" ]; then
    cp stockfish ../../fairy-stockfish
elif [ -f "fairy-stockfish" ]; then
    cp fairy-stockfish ../../fairy-stockfish
else
    echo "[build] 找不到執行檔，列出所有檔案:"
    ls -la
    exit 1
fi

cd ../..
rm -rf fs_src
chmod +x fairy-stockfish

echo "[build] 驗證引擎..."
echo -e "uci\nquit" | timeout 5 ./fairy-stockfish | grep -i "uciok\|id name" && echo "[build] ✓ 引擎正常" || echo "[build] ⚠ 驗證失敗"
echo "[build] 完成！"
