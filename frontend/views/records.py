from datetime import date, datetime, time

import pandas as pd
import streamlit as st

from utils import api, auth, ui
from utils.timefmt import TZ, TZ_LABEL, localize_column, to_api

user = auth.current_user()
can_write = user["role"] in ("admin", "user")
is_admin = user["role"] == "admin"

FLASH_KEY = "records_flash"


def flash_and_rerun(message: str, errors: list | None = None) -> None:
    ui.flash_and_rerun(FLASH_KEY, message, errors)


st.title("資料管理")
if not can_write:
    st.caption("目前角色為 viewer：僅可檢視。")
ui.show_flash(FLASH_KEY, "未匯入的列（row 為資料列序號，不含標題列）：")

# --- 篩選（form：按下套用才重跑，避免每打一個字就查詢一次）---
with st.expander("篩選與排序", expanded=False):
    with st.form("filters"):
        c1, c2, c3 = st.columns(3)
        category = c1.text_input("分類（完全符合）")
        date_range = c2.date_input(f"日期範圍（{TZ_LABEL}）", value=(), format="YYYY-MM-DD")
        size = c3.selectbox("每頁筆數", [10, 20, 50, 100], index=1)
        c4, c5, c6, c7 = st.columns(4)
        min_value = c4.number_input("最小值", value=None, format="%.2f")
        max_value = c5.number_input("最大值", value=None, format="%.2f")
        sort_by = c6.selectbox("排序欄位", ["timestamp", "value", "created_at", "title"])
        order = c7.radio("方向", ["desc", "asc"], horizontal=True)
        if st.form_submit_button("套用"):
            st.session_state["records_page"] = 1

params: dict = {"size": size, "sort_by": sort_by, "order": order}
if category:
    params["category"] = category
if len(date_range) == 2:
    # 結束日含當天整天
    params["start"] = to_api(date_range[0])
    params["end"] = to_api(date_range[1], time(23, 59, 59, 999999))
if min_value is not None:
    params["min_value"] = min_value
if max_value is not None:
    params["max_value"] = max_value

page = st.session_state.setdefault("records_page", 1)
try:
    result = api.get("/api/v1/records", params={**params, "page": page})
except api.ApiError as exc:
    st.error(exc.message)
    st.stop()
ui.pager("records_page", result["total"], result["size"])

items = result["items"]
if items:
    df = pd.DataFrame(items)
    for column in ("timestamp", "created_at", "updated_at"):
        localize_column(df, column)
    df["mine"] = df["created_by"] == user["id"]
    st.dataframe(
        df[["id", "title", "value", "category", "timestamp", "created_by", "mine", "updated_at"]],
        hide_index=True,
        width="stretch",
        column_config={
            "timestamp": st.column_config.DatetimeColumn(f"timestamp（{TZ_LABEL}）"),
            "updated_at": st.column_config.DatetimeColumn(f"updated_at（{TZ_LABEL}）"),
            "mine": st.column_config.CheckboxColumn("我建立的"),
        },
    )
else:
    st.info("沒有符合條件的資料")

if not can_write:
    st.stop()


def record_fields(prefix: str, defaults: dict | None = None) -> dict | None:
    defaults = defaults or {}
    ts = (
        datetime.fromisoformat(defaults["timestamp"]).astimezone(TZ)
        if "timestamp" in defaults
        else datetime.now(TZ)
    )
    c1, c2 = st.columns(2)
    title = c1.text_input("標題", value=defaults.get("title", ""), key=f"{prefix}_title")
    category = c2.text_input("分類", value=defaults.get("category", ""), key=f"{prefix}_cat")
    c3, c4, c5 = st.columns(3)
    value = c3.number_input(
        "數值", value=float(defaults.get("value", 0.0)), format="%.2f", key=f"{prefix}_value"
    )
    d: date = c4.date_input(f"日期（{TZ_LABEL}）", value=ts.date(), key=f"{prefix}_date")
    t: time = c5.time_input(
        f"時間（{TZ_LABEL}）",
        value=ts.time().replace(microsecond=0),
        key=f"{prefix}_time",
        step=60,
    )
    return {"title": title, "value": value, "category": category, "timestamp": to_api(d, t)}


# key + on_change="rerun"：分頁狀態由伺服器記住，寫入後重跑仍停在原分頁
create_tab, edit_tab, import_tab = st.tabs(
    ["新增", "編輯／刪除", "批量匯入"], key="records_tab", on_change="rerun"
)

with create_tab:
    with st.form("create", clear_on_submit=True):
        payload = record_fields("new")
        if st.form_submit_button("新增", type="primary"):
            try:
                created = api.post("/api/v1/records", json=payload)
            except api.ApiError as exc:
                ui.show_api_error(exc)
            else:
                flash_and_rerun(f"已新增 #{created['id']}")

with edit_tab:
    # user 只能改自己建立的；admin 可改全部（後端另有 403 把關）
    editable = [r for r in items if is_admin or r["created_by"] == user["id"]]
    if not editable:
        st.info("本頁沒有你可以編輯的資料")
    else:
        options = {f"#{r['id']} {r['title']}": r for r in editable}
        selected = options[st.selectbox("選擇資料（僅列出本頁可編輯的）", list(options))]
        with st.form(f"edit_{selected['id']}"):
            payload = record_fields(f"edit_{selected['id']}", selected)
            save, remove = st.columns(2)
            saved = save.form_submit_button("儲存修改", type="primary")
            removed = remove.form_submit_button("刪除這筆")
        if saved:
            try:
                api.put(f"/api/v1/records/{selected['id']}", json=payload)
            except api.ApiError as exc:
                ui.show_api_error(exc)
            else:
                flash_and_rerun(f"已儲存 #{selected['id']}")
        if removed:
            try:
                api.delete(f"/api/v1/records/{selected['id']}")
            except api.ApiError as exc:
                ui.show_api_error(exc)
            else:
                flash_and_rerun(f"已刪除 #{selected['id']}")

with import_tab:
    st.caption(
        "CSV 需含 title, value, category, timestamp 欄位；JSON 為物件陣列。"
        f"沒有時區的時間視為{TZ_LABEL}。上限 5 MB / 10,000 列，不合格的列會回報、其餘照常匯入。"
    )
    uploaded = st.file_uploader("選擇檔案", type=["csv", "json"])
    if uploaded is not None and st.button("開始匯入", type="primary"):
        try:
            outcome = api.post(
                "/api/v1/records/import",
                files={"file": (uploaded.name, uploaded.getvalue())},
            )
        except api.ApiError as exc:
            ui.show_api_error(exc)
        else:
            flash_and_rerun(
                f"匯入 {uploaded.name}：成功 {outcome['success_count']} 筆，"
                f"失敗 {outcome['failed_count']} 筆",
                outcome["errors"],
            )
