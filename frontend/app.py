import streamlit as st

from utils import api, auth

st.set_page_config(page_title="即時監控系統", layout="wide")


def refresh_current_user() -> None:
    # 每次重跑都向後端確認身分：角色變更立即反映在選單；token 失效則由 api 層導回登入頁
    try:
        user = api.get("/api/v1/users/me")
    except api.ApiError as exc:
        st.error(f"無法取得使用者資訊：{exc.message}")
        st.stop()
    auth.set_session(auth.get_token(), user)


if not auth.is_logged_in():
    pages = [st.Page("views/login.py", title="登入", default=True)]
else:
    refresh_current_user()
    user = auth.current_user()
    pages = [
        st.Page("views/monitor.py", title="即時監控", default=True),
        st.Page("views/records.py", title="資料管理"),
        st.Page("views/analytics.py", title="資料分析"),
    ]
    # 非 Admin 不列出系統管理頁（後端 API 另有 403 把關，這裡只是不顯示）
    if user["role"] == "admin":
        pages.append(st.Page("views/admin.py", title="系統管理"))

    with st.sidebar:
        st.write(f"**{user['username']}**（{user['role']}）")
        if st.button("登出"):
            auth.clear()
            st.rerun()

st.navigation(pages).run()
