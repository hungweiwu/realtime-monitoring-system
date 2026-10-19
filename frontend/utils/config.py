import os

# Streamlit 的 Python 程式在容器內執行，用服務名連後端
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
# 即時頁的 JS 在使用者瀏覽器執行，必須用瀏覽器連得到的位址（不能用容器服務名）
PUBLIC_WS_URL = os.environ.get("PUBLIC_WS_URL", "ws://localhost:8000")
