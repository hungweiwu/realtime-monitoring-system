from datetime import time

import pandas as pd
import streamlit as st

from utils import api
from utils.timefmt import TZ_LABEL, localize_column, to_api

st.title("資料分析")

with st.form("analytics_filters"):
    c1, c2, c3, c4 = st.columns(4)
    source_label = c1.selectbox("資料來源", ["即時資料（metrics）", "手動資料（records）"])
    category = c2.text_input("分類（留空為全部）")
    date_range = c3.date_input(f"日期範圍（{TZ_LABEL}）", value=(), format="YYYY-MM-DD")
    interval_label = c4.selectbox("趨勢區間", ["每小時", "每分鐘", "每天"])
    st.form_submit_button("套用")

params: dict = {"source": "metrics" if source_label.startswith("即時") else "records"}
if category:
    params["category"] = category
if len(date_range) == 2:
    # 結束日含當天整天
    params["start"] = to_api(date_range[0])
    params["end"] = to_api(date_range[1], time(23, 59, 59, 999999))
interval = {"每分鐘": "minute", "每小時": "hour", "每天": "day"}[interval_label]

try:
    summary = api.get("/api/v1/analytics/summary", params=params)
    categories = api.get("/api/v1/analytics/by-category", params=params)
    trend = api.get("/api/v1/analytics/trend", params={**params, "interval": interval})
except api.ApiError as exc:
    st.error(exc.message)
    st.stop()


def fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:,.2f}"


m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("筆數", f"{summary['count']:,}")
m2.metric("總和", fmt(summary["sum"]))
m3.metric("平均", fmt(summary["avg"]))
m4.metric("最大", fmt(summary["max"]))
m5.metric("最小", fmt(summary["min"]))

if summary["count"] == 0:
    st.info("沒有符合條件的資料")
    st.stop()

left, right = st.columns(2)
with left:
    st.subheader("分類聚合")
    cat_df = pd.DataFrame(categories).set_index("category")
    st.bar_chart(cat_df[["avg", "max", "min"]], stack=False)
    st.dataframe(cat_df.round(2), width="stretch")

with right:
    st.subheader(f"趨勢（{interval_label}，{TZ_LABEL}）")
    # bucket 是 UTC（例如台北 10/20 為 2026-10-19T16:00:00Z），轉成台北時間再畫，避免看起來分組錯位
    trend_df = localize_column(pd.DataFrame(trend), "bucket").set_index("bucket")
    st.line_chart(trend_df[["avg", "max", "min"]])
    st.caption(f"共 {len(trend_df)} 個區間；時間為區間起點（{TZ_LABEL}）")

st.divider()
st.download_button(
    "下載 Excel（套用目前篩選）",
    # callable：按下時才向後端產生檔案，不在每次重跑時都下載一次
    data=lambda: api.download("/api/v1/analytics/export", params),
    file_name=f"{params['source']}_analytics.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
)
