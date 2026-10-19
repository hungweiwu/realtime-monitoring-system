from datetime import time

import pandas as pd
import streamlit as st

from utils import api, auth, ui
from utils.timefmt import TZ_LABEL, localize_column, to_api

FLASH_KEY = "admin_flash"
ROLES = ["admin", "user", "viewer"]

me = auth.current_user()

st.title("系統管理")
ui.show_flash(FLASH_KEY)


def date_range_params(date_range) -> dict:
    if len(date_range) != 2:
        return {}
    # 結束日含當天整天
    return {"start": to_api(date_range[0]), "end": to_api(date_range[1], time(23, 59, 59, 999999))}


def fetch(path: str, params: dict) -> dict | None:
    try:
        return api.get(path, params=params)
    except api.ApiError as exc:
        ui.show_api_error(exc)
        return None


# on_change="rerun" + key：伺服器記住目前分頁，且 .open 只在被選取的分頁為 True，
# 只抓目前分頁的資料，不必每次重跑都打四支 API
users_tab, logs_tab, db_tab, metrics_tab = st.tabs(
    ["使用者管理", "系統日誌", "資料庫狀態", "即時資料歷史"], key="admin_tab", on_change="rerun"
)

with users_tab:
    if users_tab.open:
        page = st.session_state.setdefault("admin_users_page", 1)
        result = fetch("/api/v1/admin/users", {"page": page, "size": 50})
        if result:
            ui.pager("admin_users_page", result["total"], result["size"])
            df = localize_column(pd.DataFrame(result["items"]), "created_at")
            st.dataframe(
                df,
                hide_index=True,
                width="stretch",
                column_config={
                    "created_at": st.column_config.DatetimeColumn(f"created_at（{TZ_LABEL}）"),
                    "is_active": st.column_config.CheckboxColumn("啟用"),
                },
            )
            # 不列出自己：後端也禁止 Admin 修改自己（避免系統沒有 Admin）
            others = {
                f"#{u['id']} {u['username']}": u for u in result["items"] if u["id"] != me["id"]
            }
            if others:
                st.subheader("修改角色／啟用狀態")
                target = others[st.selectbox("使用者", list(others))]
                with st.form(f"user_{target['id']}"):
                    role = st.selectbox("角色", ROLES, index=ROLES.index(target["role"]))
                    active = st.checkbox("啟用", value=target["is_active"])
                    st.caption("變更立即生效：該帳號下一次操作就會套用新角色；停用後會被登出。")
                    if st.form_submit_button("儲存", type="primary"):
                        try:
                            api.patch(
                                f"/api/v1/admin/users/{target['id']}",
                                json={"role": role, "is_active": active},
                            )
                        except api.ApiError as exc:
                            ui.show_api_error(exc)
                        else:
                            ui.flash_and_rerun(
                                FLASH_KEY,
                                f"已更新 {target['username']}：角色 {role}，"
                                f"{'啟用' if active else '停用'}",
                            )

with logs_tab:
    if logs_tab.open:
        with st.form("log_filters"):
            c1, c2, c3 = st.columns(3)
            level = c1.selectbox("等級", ["全部", "INFO", "WARNING", "ERROR"])
            action = c2.text_input("動作（完全符合，例如 auth.login_failed）")
            log_range = c3.date_input(f"日期範圍（{TZ_LABEL}）", value=(), format="YYYY-MM-DD")
            if st.form_submit_button("套用"):
                st.session_state["admin_logs_page"] = 1
        params = {"size": 50, **date_range_params(log_range)}
        if level != "全部":
            params["level"] = level
        if action:
            params["action"] = action
        page = st.session_state.setdefault("admin_logs_page", 1)
        result = fetch("/api/v1/admin/logs", {**params, "page": page})
        if result:
            ui.pager("admin_logs_page", result["total"], result["size"])
            if result["items"]:
                df = localize_column(pd.DataFrame(result["items"]), "created_at")
                st.dataframe(
                    df[["created_at", "level", "action", "user_id", "detail"]],
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "created_at": st.column_config.DatetimeColumn(f"時間（{TZ_LABEL}）")
                    },
                )
            else:
                st.info("沒有符合條件的日誌")

with db_tab:
    if db_tab.open:
        st.button("重新整理", key="db_refresh")
        status = fetch("/api/v1/admin/db-status", {})
        if status:
            db = status["database"]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("資料庫連線", "正常" if db["ok"] else "異常")
            c2.metric("查詢延遲", f"{db['latency_ms']} ms" if db["latency_ms"] is not None else "—")
            c3.metric("待寫入 buffer", status["buffer"]["pending"])
            c4.metric("WebSocket 連線數", status["websocket_connections"])

            pool = status["pool"]
            st.subheader("連接池")
            if "size" in pool:
                p1, p2, p3, p4 = st.columns(4)
                p1.metric("pool size", pool["size"])
                p2.metric("使用中", pool["checked_out"])
                p3.metric("閒置", pool["checked_in"])
                p4.metric("超量使用中", f"{pool['overflow_in_use']} / {pool['max_overflow']}")
            else:
                st.caption(f"{pool['class']}：無連接池統計")
            if status["buffer"]["dropped"]:
                st.warning(f"DB 曾長時間無法寫入，buffer 已丟棄 {status['buffer']['dropped']} 筆")

            st.subheader("各表筆數")
            st.dataframe(
                pd.DataFrame(status["tables"].items(), columns=["table", "rows"]),
                hide_index=True,
            )

with metrics_tab:
    if metrics_tab.open:
        with st.form("metric_filters"):
            c1, c2, c3 = st.columns(3)
            metric_range = c1.date_input(f"日期範圍（{TZ_LABEL}）", value=(), format="YYYY-MM-DD")
            category = c2.text_input("分類")
            anomaly_only = c3.checkbox("只看異常")
            if st.form_submit_button("套用"):
                st.session_state["admin_metrics_page"] = 1
        params = {"size": 100, "anomaly_only": anomaly_only, **date_range_params(metric_range)}
        if category:
            params["category"] = category
        page = st.session_state.setdefault("admin_metrics_page", 1)
        result = fetch("/api/v1/admin/metrics", {**params, "page": page})
        if result:
            ui.pager("admin_metrics_page", result["total"], result["size"])
            if result["items"]:
                df = localize_column(pd.DataFrame(result["items"]), "timestamp")
                st.dataframe(
                    df[["id", "timestamp", "category", "value", "is_anomaly"]],
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "timestamp": st.column_config.DatetimeColumn(
                            f"timestamp（{TZ_LABEL}）", format="YYYY-MM-DD HH:mm:ss"
                        ),
                        "is_anomaly": st.column_config.CheckboxColumn("異常"),
                    },
                )
            else:
                st.info("沒有符合條件的資料")
