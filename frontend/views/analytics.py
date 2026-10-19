from datetime import time
from functools import partial

import pandas as pd
import streamlit as st

from utils import api, auth
from utils.timefmt import TZ_LABEL, localize_column, to_api


def main() -> None:
    # 以函式 return 結束頁面，不用 st.stop()：在 st.navigation 的頁面中呼叫 st.stop()，
    # 瀏覽器端之後點側邊欄切頁會沒有反應（viewer 在資料管理頁被卡住）
    st.title("資料分析")

    with st.form("analytics_filters"):
        c1, c2, c3, c4 = st.columns(4)
        source_label = c1.selectbox("資料來源", ["即時資料（metrics）", "手動資料（records）"])
        category = c2.text_input("分類（留空為全部）")
        date_range = c3.date_input(f"日期範圍（{TZ_LABEL}）", value=(), format="YYYY-MM-DD")
        # 預設每分鐘：系統剛啟動時只有幾分鐘的資料，以小時分組只有一個點、畫不出趨勢
        interval_label = c4.selectbox("趨勢區間", ["每分鐘", "每小時", "每天"])
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
        return

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
        return

    left, right = st.columns(2)
    with left:
        st.subheader("分類聚合")
        cat_df = pd.DataFrame(categories).set_index("category")
        st.bar_chart(cat_df[["avg", "max", "min"]], stack=False)
        st.dataframe(cat_df.round(2), width="stretch")

    with right:
        st.subheader(f"趨勢（{interval_label}，{TZ_LABEL}）")
        # bucket 是 UTC（例如台北 10/20 為 2026-10-19T16:00:00Z），
        # 轉成台北時間再畫，避免看起來分組錯位
        trend_df = localize_column(pd.DataFrame(trend), "bucket").set_index("bucket")
        if len(trend_df) < 2:
            # 折線至少要兩個點才畫得出來，只有一個區間時改用長條圖
            st.bar_chart(trend_df[["avg", "max", "min"]], stack=False)
        else:
            st.line_chart(trend_df[["avg", "max", "min"]])
        st.caption(f"共 {len(trend_df)} 個區間；時間為區間起點（{TZ_LABEL}）")

    st.divider()
    # token 在渲染時取出：下載的 callable 在背景執行緒執行，屆時讀不到 session_state
    export_token = auth.get_token()
    st.download_button(
        "下載 Excel（套用目前篩選）",
        # callable：按下時才向後端產生檔案，不在每次重跑時都下載一次
        data=partial(api.download, "/api/v1/analytics/export", params, export_token),
        file_name=f"{params['source']}_analytics.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )


main()
