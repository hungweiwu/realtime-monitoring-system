# Implementation Plan：即時資料分析與監控系統

> 依據：`SPEC.md`（已核准）。任務細節與驗收條件見 `tasks/todo.md`。
> 截止：2026/10/21（三）17:00。

## Overview

從空 repo 開始，依 SPEC 第 13 節優先序分五個階段實作：
1. 基礎建設：容器、DB、認證
2. Records 資料管理
3. 即時監控與前端骨架：最高風險的 Streamlit 方案 A 提早做，越早失敗越好
4. 資料分析與對應前端頁面
5. Admin 與交付

每個任務完成時，系統都要能 `docker compose up` 跑起來，且該任務的測試全綠。

## Architecture Decisions（補充 SPEC 未寫的實作層決策）

- **時間欄位用 TypeDecorator `UTCDateTime`**：寫入時轉 UTC 並去掉 tzinfo，讀出時補回 UTC tzinfo。理由：MariaDB `DATETIME` 不存時區，直接把 aware datetime 交給 asyncmy，行為依驅動而定。統一在一個地方處理，其他程式碼一律只碰 aware datetime。
- **backend builder 階段預裝 `build-essential`**：開發機是 arm64，Docker 會建 linux/aarch64 映像。asyncmy 是 C 擴充，aarch64 若沒有現成 wheel 就得在 builder 編譯。編譯工具只留在 builder，runtime 映像不含，這也正是多階段 Dockerfile 的實際用途（可寫進 README）。
- **`log_action()` 放在 service 層的共用函式**：與業務操作同一個 session、同一個 transaction 提交。業務失敗回滾時，日誌也不會留下假紀錄。
- **前端骨架（登入 + navigation）排在即時頁之前**：方案 A 需要登入後的 token 才能連 WS。
- **方案 A 排在 10/20 中段**：若 2 小時內做不完，當天還有時間退回 B，不會拖到交件日。

## 依賴圖

```
T1 骨架+compose(db,api,/health)
 └─ T2 models+Alembic
     └─ T3 錯誤處理/日誌/測試基礎
         └─ T4 認證+角色+seed
             ├─ T5 Records CRUD ─ T6 列表查詢 ─ T7 匯入
             ├─ T8 產生器+批次寫入 ─ T9 WS+latest ─┐
             ├─ T10 前端骨架(登入) ─────────────────┴─ T11 即時頁(方案A)
             ├─ T12 分析API ─ T13 Excel 匯出
             │     └─ T14 Records頁+分析頁（亦依賴 T6、T7、T10）
             └─ T15 Admin API ─ T16 Admin頁（亦依賴 T10）
T17 README+架構圖（依賴所有功能）─ T18 交件驗證
```

## Task List

### Phase 1：基礎建設（10/19 晚，約 4.5h）
- [ ] T1：專案骨架與 Docker Compose（db + api，`/health`）
- [ ] T2：資料模型與 Alembic 初始 migration
- [ ] T3：統一錯誤處理、日誌、測試基礎設施
- [ ] T4：認證、角色權限與種子帳號

**Checkpoint 1**：`docker compose up` 起得來；Swagger 能 Authorize；三個種子帳號登入成功；pytest 全綠

### Phase 2：Records（10/20 上午，約 3h）
- [ ] T5：Records CRUD 與建立者權限
- [ ] T6：Records 列表（分頁、篩選、排序）
- [ ] T7：CSV / JSON 批量匯入

**Checkpoint 2**：Swagger 走完 records 全流程；三種角色權限正確；pytest 全綠

### Phase 3：即時監控與前端骨架（10/20 下午，約 5h）
- [ ] T8：資料產生器、異常標記、批次寫入
- [ ] T9：WebSocket 推送與 `/metrics/latest`
- [ ] T10：Streamlit 骨架（登入、登出、依角色 navigation）
- [ ] T11：即時監控頁（方案 A，2h 時限，超時退回 B）

**Checkpoint 3**：前端登入後即時圖每秒更新，異常變色；`metrics` 表有批次寫入的 log；`docker compose restart api` log 看得到關機 flush

### Phase 4：資料分析（10/20 晚，約 3.5h）
- [ ] T12：分析 API（summary / by-category / trend，`source` 參數）
- [ ] T13：Excel 匯出
- [ ] T14：前端 Records 頁與分析頁

**Checkpoint 4**：四個功能模組中三個可在前端操作；pytest 全綠

### Phase 5：Admin 與交付（10/21，至 12:00）
- [ ] T15：Admin API（使用者、日誌、DB 狀態、metrics 歷史）
- [ ] T16：前端系統管理頁
- [ ] T17：README、架構圖、`.env.example`、範例資料定稿
- [ ] T18：交件驗證（乾淨環境、grep、`/review`）

**Checkpoint 5（交件前）**：SPEC 第 12 節全部勾選

## 時程對照與降級點

| 時間點 | 應完成 | 若落後 |
|---|---|---|
| 10/19 24:00 | T1–T4 | T3 測試基礎設施可延到 10/20 早上，但 T4 必須完成 |
| 10/20 12:00 | T5–T7 | T7 匯入先只做 CSV |
| 10/20 18:00 | T8–T11 | T11 退回方案 B；T8 的「flush 失敗放回 buffer」延後，README 標註「已設計、未實作」 |
| 10/20 24:00 | T12–T14 | T14 分析頁只做 summary + trend 圖；T13 只做 data 工作表 |
| 10/21 10:00 | T15–T16 | T16 只做使用者管理與 DB 狀態 |
| 10/21 12:00 | 開始 T17 | **不可延**，其他未完成項目直接砍 |
| 10/21 15:00 | T18 完成 | 留 2 小時緩衝回信 |

## Risks and Mitigations

| 風險 | 影響 | 對策 |
|---|---|---|
| asyncmy 在 linux/aarch64 沒有 wheel，需要編譯 | 高（T1 卡住就全部卡住） | builder 階段裝 build-essential；T1 第一件事就是驗證 `docker compose build` 成功。真的失敗再問你是否改用 aiomysql（題目指定 asyncmy，不輕易換） |
| Alembic async `env.py` 與 autogenerate 設定錯誤 | 中 | 用 `alembic init -t async` 範本，照官方文件設定 `target_metadata` |
| aware / naive datetime 混用 | 中 | `UTCDateTime` TypeDecorator 加單元測試 |
| Streamlit `components.html` 的 iframe 內 WS 連線或 Chart.js 載入有問題 | 中 | 2h 時限，超時退回方案 B（`/metrics/latest` 在 T9 已備好） |
| `func.date_format` 分組在 ORM 中的寫法與排序 | 低 | T12 測試在 MariaDB 上驗證 |
| 關機 flush 沒執行（SIGTERM 沒送到 uvicorn） | 中 | entrypoint 用 `exec`；Checkpoint 3 用 `docker compose restart api` 實測 |
| 時程落後 | 高 | 照上表的降級點；README 與「一行跑起來」不可砍 |

## Open Questions

無。
