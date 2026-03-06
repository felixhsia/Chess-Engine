# app.py — 象棋軍師後端 v3
# 整合 Fairy-Stockfish 專業引擎 + Claude Vision + Claude 戰略說明

import os, subprocess, threading, time, requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=False)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ENGINE_PATH = os.environ.get("ENGINE_PATH", "./fairy-stockfish")

# ─────────────────────────────────────────
# Fairy-Stockfish UCI 封裝
# ─────────────────────────────────────────

class FairyStockfish:
    def __init__(self, path=ENGINE_PATH):
        self.path = path
        self.proc = None
        self.lock = threading.Lock()

    def start(self):
        if self.proc and self.proc.poll() is None:
            return True
        try:
            self.proc = subprocess.Popen(
                [self.path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                universal_newlines=True,
                bufsize=1,
            )
            self._send("uci")
            self._wait_for("uciok", timeout=5)
            self._send("setoption name UCI_Variant value xiangqi")
            self._send("isready")
            self._wait_for("readyok", timeout=5)
            return True
        except Exception as e:
            print(f"[Engine] 啟動失敗: {e}")
            self.proc = None
            return False

    def _send(self, cmd):
        self.proc.stdin.write(cmd + "\n")
        self.proc.stdin.flush()

    def _wait_for(self, keyword, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.proc.stdout.readline().strip()
            if keyword in line:
                return line
        return ""

    def analyse(self, fen, depth=15, multipv=3):
        """
        回傳前 multipv 個最佳走法，每個含 move, score, pv
        """
        with self.lock:
            if not self.start():
                return []
            try:
                self._send("ucinewgame")
                self._send(f"position fen {fen}")
                self._send(f"setoption name MultiPV value {multipv}")
                self._send(f"go depth {depth}")

                results = {}
                deadline = time.time() + 15
                while time.time() < deadline:
                    line = self.proc.stdout.readline().strip()
                    if line.startswith("bestmove"):
                        break
                    if "multipv" in line and " pv " in line:
                        parts = line.split()
                        try:
                            mpv_idx = parts.index("multipv")
                            pv_idx  = parts.index("pv")
                            cp_score = None
                            mate_score = None
                            if "score cp" in line:
                                sc_idx = parts.index("cp", parts.index("score"))
                                cp_score = int(parts[sc_idx + 1])
                            elif "score mate" in line:
                                sc_idx = parts.index("mate", parts.index("score"))
                                mate_score = int(parts[sc_idx + 1])
                            rank = int(parts[mpv_idx + 1])
                            best_move = parts[pv_idx + 1] if pv_idx + 1 < len(parts) else None
                            if best_move:
                                results[rank] = {
                                    "move": best_move,
                                    "score_cp": cp_score,
                                    "score_mate": mate_score,
                                    "pv": parts[pv_idx + 1: pv_idx + 5],
                                }
                        except (ValueError, IndexError):
                            pass

                return [results[k] for k in sorted(results.keys()) if k in results]
            except Exception as e:
                print(f"[Engine] 分析失敗: {e}")
                return []

engine = FairyStockfish()

# ─────────────────────────────────────────
# 棋盤 array → FEN 轉換
# ─────────────────────────────────────────
# 我們的 array: row0=黑方底線, row9=紅方底線
# 紅方大寫: K仕A象B俥R傌N炮C兵P
# 黑方小寫: k士a象b車r馬n炮c卒p
INT_TO_FEN = {
    1:'K', 2:'A', 3:'B', 4:'R', 5:'N', 6:'C', 7:'P',
   -1:'k',-2:'a',-3:'b',-4:'r',-5:'n',-6:'c',-7:'p',
}

def board_to_fen(board, turn="w"):
    rows = []
    for row in board:
        fen_row = ""
        empty = 0
        for cell in row:
            if cell == 0:
                empty += 1
            else:
                if empty:
                    fen_row += str(empty)
                    empty = 0
                fen_row += INT_TO_FEN.get(cell, "?")
        if empty:
            fen_row += str(empty)
        rows.append(fen_row)
    return "/".join(rows) + f" {turn} - - 0 1"

# UCI move (e.g. "e2e4") → 中文走法記譜
# UCI 座標: a-i 欄（左到右）, 0-9 列（由下往上，但象棋9是黑底0是紅底要注意）
# Fairy-Stockfish Xiangqi: file a-i = col 0-8, rank 0-9
# rank 0 = row 9 (紅底), rank 9 = row 0 (黑底)

PIECE_CN_RED   = {1:'帥',2:'仕',3:'相',4:'俥',5:'傌',6:'炮',7:'兵'}
PIECE_CN_BLACK = {-1:'將',-2:'士',-3:'象',-4:'車',-5:'馬',-6:'包',-7:'卒'}

def parse_uci_xiangqi(uci_move):
    """
    解析象棋 UCI 走法，支援兩位數 rank（如 d10e9）
    回傳 (c1, r1_uci, c2, r2_uci) 或 None
    """
    # 格式: [a-i][0-9]{1,2}[a-i][0-9]{1,2}
    import re
    m = re.match(r'^([a-i])(\d{1,2})([a-i])(\d{1,2})$', uci_move)
    if not m:
        return None
    c1 = ord(m.group(1)) - ord('a')
    r1 = int(m.group(2))
    c2 = ord(m.group(3)) - ord('a')
    r2 = int(m.group(4))
    return c1, r1, c2, r2

COL_NAMES = ['一','二','三','四','五','六','七','八','九']

def uci_to_cn(uci_move, board):
    """
    將象棋 UCI 走法轉為中文記譜
    Fairy-Stockfish Xiangqi: rank 0 = 紅方底線(row9), rank 9 = 黑方底線(row0)
    """
    if not uci_move:
        return uci_move
    parsed = parse_uci_xiangqi(uci_move)
    if not parsed:
        return uci_move
    try:
        c1, r1_uci, c2, r2_uci = parsed

        # Fairy-Stockfish 象棋 rank 是 1-indexed: rank1=紅底(row9), rank10=黑底(row0)
        row1 = 10 - r1_uci
        row2 = 10 - r2_uci

        if row1 < 0 or row1 > 9 or row2 < 0 or row2 > 9:
            return uci_move

        piece = board[row1][c1]
        if piece == 0:
            return uci_move

        if piece > 0:
            # 紅方：欄位從右往左，col8=一, col0=九
            name = PIECE_CN_RED.get(piece, '?')
            from_col = COL_NAMES[8 - c1]
            to_col   = COL_NAMES[8 - c2]
        else:
            # 黑方：欄位從左往右，col0=一, col8=九
            name = PIECE_CN_BLACK.get(piece, '?')
            from_col = COL_NAMES[c1]
            to_col   = COL_NAMES[c2]

        if row1 == row2:
            return f"{name}{from_col}平{to_col}"

        # 進退判斷：紅方 row 數字減小=進，黑方 row 數字增大=進
        if (piece > 0 and row2 < row1) or (piece < 0 and row2 > row1):
            action = "進"
        else:
            action = "退"

        steps = abs(row2 - row1)
        return f"{name}{from_col}{action}{steps}"
    except Exception as e:
        print(f"[uci_to_cn] 錯誤: {e}, move={uci_move}")
        return uci_move

def score_display(result):
    if result.get("score_mate") is not None:
        m = result["score_mate"]
        return f"M{abs(m)}" if m > 0 else f"-M{abs(m)}"
    cp = result.get("score_cp", 0) or 0
    return f"{cp/100:+.1f}"

# ─────────────────────────────────────────
# Claude API 呼叫
# ─────────────────────────────────────────

def call_claude(payload):
    if not ANTHROPIC_API_KEY:
        return None, "未設定 ANTHROPIC_API_KEY"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    resp = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        return None, f"Anthropic API 錯誤 {resp.status_code}: {resp.text[:300]}"
    return resp.json(), None

# ─────────────────────────────────────────
# 路由
# ─────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    eng_ok = engine.start()
    return jsonify({
        "status": "ok",
        "key_set": bool(ANTHROPIC_API_KEY),
        "engine": "ready" if eng_ok else "unavailable",
    })

@app.route("/api/messages", methods=["POST", "OPTIONS"])
def proxy_messages():
    if request.method == "OPTIONS":
        r = jsonify({"status": "ok"})
        r.headers["Access-Control-Allow-Origin"] = "*"
        r.headers["Access-Control-Allow-Headers"] = "Content-Type"
        r.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        return r, 200
    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"error": {"message": "Invalid JSON"}}), 400
    if not payload.get("model", "").startswith("claude-"):
        return jsonify({"error": {"message": "不允許的模型"}}), 403
    result, err = call_claude(payload)
    if err:
        return jsonify({"error": {"message": err}}), 500
    return jsonify(result)

@app.route("/api/engine", methods=["POST", "OPTIONS"])
def engine_analyse():
    """
    前端傳入: { board: [[...10x9...]], turn: "red"|"black" }
    回傳: { moves: [{move_uci, move_cn, score, pv_cn}] }
    """
    if request.method == "OPTIONS":
        r = jsonify({"status": "ok"})
        r.headers["Access-Control-Allow-Origin"] = "*"
        r.headers["Access-Control-Allow-Headers"] = "Content-Type"
        r.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        return r, 200

    data = request.get_json(force=True)
    board = data.get("board")
    turn  = "w" if data.get("turn", "red") == "red" else "b"
    depth = int(data.get("depth", 15))

    if not board:
        return jsonify({"error": "缺少 board"}), 400

    fen = board_to_fen(board, turn)
    print(f"[Engine] FEN: {fen}")

    results = engine.analyse(fen, depth=depth, multipv=3)
    if not results:
        return jsonify({"error": "引擎分析失敗，請確認引擎已正確安裝"}), 500

    moves = []
    for r in results:
        uci = r["move"]
        cn  = uci_to_cn(uci, board)
        moves.append({
            "move_uci": uci,
            "move_cn":  cn,
            "score":    score_display(r),
            "score_cp": r.get("score_cp"),
            "score_mate": r.get("score_mate"),
            "pv":       r.get("pv", []),
        })

    return jsonify({"fen": fen, "moves": moves})


if __name__ == "__main__":
    engine.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
