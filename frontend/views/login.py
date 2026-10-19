import streamlit as st

from utils import api, auth

st.title("即時資料分析與監控系統")

if flash := st.session_state.pop("flash", None):
    st.warning(flash)

login_tab, register_tab = st.tabs(["登入", "註冊"])

with login_tab:
    with st.form("login"):
        username = st.text_input("帳號")
        password = st.text_input("密碼", type="password")
        submitted = st.form_submit_button("登入", type="primary")
    if submitted and not (username and password):
        st.error("請輸入帳號與密碼")
    elif submitted:
        try:
            token = api.post(
                "/api/v1/auth/login",
                data={"username": username, "password": password},
                authenticated=False,
            )["access_token"]
            user = api.get(
                "/api/v1/users/me",
                headers={"Authorization": f"Bearer {token}"},
                authenticated=False,
            )
        except api.ApiError as exc:
            st.error(exc.message)
        else:
            auth.set_session(token, user)
            st.rerun()

with register_tab:
    with st.form("register"):
        new_username = st.text_input("帳號（3–32 字元，英數字與底線）")
        new_password = st.text_input("密碼（至少 8 字元）", type="password")
        registered = st.form_submit_button("註冊")
    if registered:
        try:
            api.post(
                "/api/v1/auth/register",
                json={"username": new_username, "password": new_password},
                authenticated=False,
            )
        except api.ApiError as exc:
            st.error(exc.message)
            if exc.details:
                for detail in exc.details:
                    st.caption(f"{detail['loc'][-1]}：{detail['msg']}")
        else:
            st.success("註冊成功，請切換到「登入」分頁登入（預設角色：user）")
