#!/bin/bash
# build.sh — 偵測架構並下載對應的 Fairy-Stockfish
set -e

pip install -r requirements.txt

echo "[build] 系統架構: $(uname -m)"
echo "[build] 系統資訊: $(uname -a)"

ARCH=$(uname -m)

if [ -f "fairy-stockfish" ]; then
    echo "[build] 引擎已存在，測試是否可執行..."
    if echo -e "uci\nquit" | timeout 5 ./fairy-stockfish 2>/dev/null | grep -q "uciok"; then
        echo "[build] ✓ 引擎正常，跳過重新安裝"
        exit 0
    else
        echo "[build] 引擎無法執行，重新安裝..."
        rm -f fairy-stockfish
    fi
fi

if [ "$ARCH" = "x86_64" ]; then
    echo "[build] 下載 x86-64 預編譯版本..."
    # 嘗試多個來源
    URLS=(
        "https://github.com/fairy-stockfish/Fairy-Stockfish/releases/download/fairy-sf-14/fairy-stockfish-largeboard_x86-64"
        "https://github.com/ianfab/Fairy-Stockfish/releases/download/fairy-sf-14/fairy-stockfish-largeboard_x86-64"
    )
    for URL in "${URLS[@]}"; do
        echo "[build] 嘗試: $URL"
        if curl -fL "$URL" -o fairy-stockfish 2>/dev/null; then
            chmod +x fairy-stockfish
            if echo -e "uci\nquit" | timeout 5 ./fairy-stockfish 2>/dev/null | grep -q "uciok"; then
                echo "[build] ✓ 預編譯版本正常"
                exit 0
            fi
        fi
        rm -f fairy-stockfish
    done
    echo "[build] 預編譯版本失敗，改為從源碼編譯..."
fi

# 從源碼編譯（ARM 或 x86 預編譯失敗時）
echo "[build] 安裝編譯工具..."
apt-get update -qq && apt-get install -y -qq g++ make git

echo "[build] 下載源碼..."
rm -rf fs_src
git clone --depth=1 https://github.com/fairy-stockfish/Fairy-Stockfish.git fs_src

echo "[build] 編譯中..."
cd fs_src/src

if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
    make -j2 build ARCH=armv8 COMP=gcc largeboards=yes 2>&1 | tail -5
else
    make -j2 build ARCH=x86-64-modern COMP=gcc largeboards=yes 2>&1 | tail -5
fi

# 找執行檔
BUILT=$(find . -maxdepth 1 -type f -executable ! -name "*.o" | head -1)
if [ -z "$BUILT" ]; then
    echo "[build] ✗ 找不到編譯結果"
    ls -la
    exit 1
fi

cp "$BUILT" ../../fairy-stockfish
cd ../..
rm -rf fs_src
chmod +x fairy-stockfish

echo "[build] 驗證..."
echo -e "uci\nquit" | timeout 5 ./fairy-stockfish | grep "uciok" && echo "[build] ✓ 完成！" || { echo "[build] ✗ 驗證失敗"; exit 1; }
