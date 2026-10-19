from typing import Any

import httpx
import streamlit as st

from utils import auth
from utils.config import API_BASE_URL


class ApiError(Exception):
    def __init__(self, status_code: int, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.details = details


def _error_from(resp: httpx.Response) -> ApiError:
    try:
        error = resp.json()["error"]
        return ApiError(resp.status_code, error["message"], error.get("details"))
    except (ValueError, KeyError, TypeError):
        return ApiError(resp.status_code, resp.text or resp.reason_phrase)


def request(method: str, path: str, *, authenticated: bool = True, **kwargs: Any) -> httpx.Response:
    """呼叫後端 API。

    401 時清除登入狀態並重跑：token 過期或帳號被停用時，使用者下一次操作就會回到登入頁。
    """
    headers = kwargs.pop("headers", {})
    if authenticated and (token := auth.get_token()):
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.request(method, f"{API_BASE_URL}{path}", headers=headers, timeout=30, **kwargs)
    except httpx.HTTPError as exc:
        raise ApiError(0, f"無法連線到後端：{exc}") from exc

    if resp.status_code == 401 and authenticated:
        auth.clear()
        st.session_state["flash"] = "登入已失效，請重新登入"
        st.rerun()
    if resp.is_error:
        raise _error_from(resp)
    return resp


def get(path: str, **kwargs: Any) -> Any:
    return request("GET", path, **kwargs).json()


def post(path: str, **kwargs: Any) -> Any:
    return request("POST", path, **kwargs).json()
