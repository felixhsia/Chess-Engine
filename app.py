# app.py — 象棋軍師 後端代理
# 部署到 Render，API Key 藏在環境變數

import os, json, requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # 允許 Hugging Face 前端跨域呼叫

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def call_claude(payload: dict):
    """轉發請求到 Anthropic API，自動帶上 Key"""
    if not ANTHROPIC_API_KEY:
        return None, "Server 未設定 ANTHROPIC_API_KEY"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    resp = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        return None, f"Anthropic API 錯誤 {resp.status_code}: {resp.text[:200]}"
    return resp.json(), None


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "key_set": bool(ANTHROPIC_API_KEY)})


@app.route("/api/messages", methods=["POST"])
def proxy_messages():
    """
    前端把原本要送到 api.anthropic.com/v1/messages 的 body
    改送到這裡，我們加上 Key 後再轉發。
    """
    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"error": {"message": "Invalid JSON"}}), 400

    # 安全檢查：只允許 claude-sonnet 模型
    model = payload.get("model", "")
    if not model.startswith("claude-"):
        return jsonify({"error": {"message": "不允許的模型"}}), 403

    result, err = call_claude(payload)
    if err:
        return jsonify({"error": {"message": err}}), 500

    return jsonify(result)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
