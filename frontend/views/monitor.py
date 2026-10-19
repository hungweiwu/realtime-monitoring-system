import json
from pathlib import Path

import streamlit as st

from utils import api, auth
from utils.config import PUBLIC_WS_URL

WINDOW_SIZE = 60
TEMPLATE = (Path(__file__).parent.parent / "templates" / "monitor.html").read_text(encoding="utf-8")

st.title("即時監控")
st.caption(
    "資料由瀏覽器直接透過 WebSocket 接收，每秒更新；"
    "紅點為超出閾值的異常資料。此頁刻意不放互動元件，避免 Streamlit 重跑導致連線重建。"
)

# 初始資料由 Python 端（容器內連 api:8000）先抓好注入：iframe 內的 JS 直接 fetch 後端會被 CORS 擋
try:
    initial = api.get("/api/v1/metrics/latest", params={"limit": WINDOW_SIZE})
except api.ApiError:
    # 例如 docker compose restart api 期間：不顯示 traceback，先以空圖表開始，WS 恢復後自動補上
    st.warning("暫時無法取得即時資料（後端可能正在重啟），連線恢復後圖表會自動更新。")
    initial = []
config = {
    "wsUrl": PUBLIC_WS_URL,
    "token": auth.get_token(),
    "initial": initial,
    "windowSize": WINDOW_SIZE,
}
# json.dumps 產生合法的 JS 字面值；再把 < > & 轉成 \u 跳脫（在 JSON 字串內意義不變），
# HTML 解析器在 script 區塊內就看不到 "</script>" 或 "<!--"，資料無法提前結束或改變 script 狀態
config_js = (
    json.dumps(config, ensure_ascii=False)
    .replace("<", "\\u003c")
    .replace(">", "\\u003e")
    .replace("&", "\\u0026")
)
st.iframe(TEMPLATE.replace("__CONFIG__", config_js), height=560)
