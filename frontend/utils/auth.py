"""登入狀態存在 st.session_state：每個瀏覽器分頁一份，重新整理頁面就會清空（需重新登入）。"""

from typing import Any

import streamlit as st

TOKEN_KEY = "access_token"
USER_KEY = "current_user"


def get_token() -> str | None:
    return st.session_state.get(TOKEN_KEY)


def current_user() -> dict[str, Any] | None:
    return st.session_state.get(USER_KEY)


def is_logged_in() -> bool:
    return get_token() is not None


def set_session(token: str, user: dict[str, Any]) -> None:
    st.session_state[TOKEN_KEY] = token
    st.session_state[USER_KEY] = user


def clear() -> None:
    st.session_state.pop(TOKEN_KEY, None)
    st.session_state.pop(USER_KEY, None)
