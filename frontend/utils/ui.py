"""頁面間共用的小元件。"""

import pandas as pd
import streamlit as st


def flash_and_rerun(key: str, message: str, errors: list | None = None) -> None:
    """寫入操作完成後重跑以刷新資料；訊息先存進 session_state，重跑後由 show_flash 顯示一次。

    直接 st.success 再 st.rerun 的話，訊息會在重跑時消失。
    """
    st.session_state[key] = {"message": message, "errors": errors or []}
    st.rerun()


def show_flash(key: str, errors_caption: str = "") -> None:
    if flash := st.session_state.pop(key, None):
        st.success(flash["message"])
        if flash["errors"]:
            if errors_caption:
                st.caption(errors_caption)
            st.dataframe(pd.DataFrame(flash["errors"]), hide_index=True)


def pager(key: str, total: int, size: int) -> int:
    """上一頁／下一頁導覽，回傳目前頁碼（存在 session_state[key]）。"""
    total_pages = max(1, -(-total // size))
    requested = st.session_state.setdefault(key, 1)
    page = min(requested, total_pages)
    if page != requested:
        # 例如刪掉最後一頁唯一一筆：本次資料是用超出範圍的頁碼抓的（空的），
        # 寫回合法頁碼後重跑，重新抓正確那一頁
        st.session_state[key] = page
        st.rerun()
    prev, label, nxt = st.columns([1, 2, 1])
    if prev.button("← 上一頁", key=f"{key}_prev", disabled=page <= 1):
        st.session_state[key] = page - 1
        st.rerun()
    label.markdown(f"第 **{page} / {total_pages}** 頁，共 **{total}** 筆")
    if nxt.button("下一頁 →", key=f"{key}_next", disabled=page >= total_pages):
        st.session_state[key] = page + 1
        st.rerun()
    return page


def show_api_error(exc) -> None:
    st.error(exc.message)
    for detail in exc.details or []:
        if isinstance(detail, dict) and "loc" in detail:
            st.caption(f"{detail['loc'][-1]}：{detail['msg']}")
