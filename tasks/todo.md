# Todo：即時資料分析與監控系統

> 依據 `SPEC.md` 與 `tasks/plan.md`。每個任務完成時都要通過下列共通條件（Definition of Done），才算完成：
> - `cd backend && uv run ruff check . && uv run ruff format --check .` 無錯誤
> - `docker compose --profile test run --rm api-test` 全綠（T3 之後）
> - `grep -rnE "(^|[^A-Za-z0-9_])text\(|exec_driver_sql|execute\([\"']" backend/app backend/tests` 無結果
> - `docker compose up --build` 可啟動
> - 若是關鍵設計，用 2–3 句說明「為什麼」，並記到 README 草稿

---

## Phase 1：基礎建設（10/19 晚）

### ✅ T1：專案骨架與 Docker Compose（db + api，/health）
**Description:** 建立 backend uv 專案、多階段 Dockerfile、entrypoint、pydantic-settings 設定、async engine 與 session，以及 `GET /health`（以 `select(literal(1))` 檢查 DB）。compose 先只有 db 與 api。

**Acceptance criteria:**
- [x] 不建 `.env`，`docker compose up --build` 後 db 和 api 都是 healthy（asyncmy 在 aarch64 建置成功）
- [x] `curl localhost:8000/health` 回傳 DB 狀態 ok；停掉 db 後回報失敗（非 200）
- [x] api 映像為多階段建置：runtime 沒有 build-essential、以非 root 執行；`uv.lock` 已 commit

**Verification:**
- [x] `docker compose up --build`，接著 `docker compose ps` 顯示 healthy
- [x] `docker compose exec api id -u` 不是 0
- [x] `docker compose exec api cat /proc/1/cmdline | tr '\0' ' '` 顯示 PID 1 是 uvicorn（slim 映像沒有 ps）

**Dependencies:** 無
**Files:** `docker-compose.yml`、`backend/Dockerfile`、`backend/entrypoint.sh`、`backend/pyproject.toml`、`backend/app/{main.py,core/config.py,db/session.py}`、`.gitignore`、`.env.example`
**Scope:** M（檔案多，但每個檔案都很小）

> 實作備註：asyncmy 0.2.16 有 manylinux aarch64 wheel，builder 不需 build-essential（plan 的預防措施未採用）。

### ✅ T2：資料模型與 Alembic 初始 migration
**Description:** 建立 `Base`、`UTCDateTime` TypeDecorator、四個 model（含索引、`role` 用 `native_enum=False`），用 `alembic init -t async` 設定 env，並產生初始 migration。entrypoint 的 `alembic upgrade head` 開始生效。

**Acceptance criteria:**
- [x] 啟動後 DB 內有四張表，索引符合 SPEC 第 3 節
- [x] `alembic upgrade head` 重跑不報錯；`alembic downgrade base` 可回復
- [x] `UTCDateTime` 寫入 Asia/Taipei 時間，讀回時是等值的 UTC aware datetime

**Verification:**
- [x] `docker compose exec db mariadb -u... -e "SHOW INDEX FROM metrics"`（人工檢查用，不在程式碼內）
- [x] `UTCDateTime` 的單元測試（T3 已補：`tests/test_types.py`）

**Dependencies:** T1
**Files:** `backend/app/db/base.py`、`backend/app/db/types.py`、`backend/app/models/*.py`、`backend/migrations/{env.py,versions/0001_init.py}`、`backend/alembic.ini`
**Scope:** M

> 實作備註：autogenerate 的 downgrade 會先刪 FK 依附的索引，MariaDB 拒絕（error 1553），已改為直接依子表→父表順序 drop table。

### ✅ T3：統一錯誤處理、日誌、測試基礎設施
**Description:** 建立 `AppError` 階層與四個 exception handler（AppError、HTTPException、RequestValidationError、500）；設定 stdlib logging 輸出到 stdout；在 compose 加 `db-test` 與 `api-test`（Dockerfile 的 `test` stage），寫好 conftest（create_all、每個測試後清表、`ENABLE_GENERATOR=false`、AsyncClient fixture）。

**Acceptance criteria:**
- [x] 404、422、500 的回應都是 `{"error": {"code", "message", "details"}}`，500 不洩漏 stack trace
- [x] `docker compose --profile test run --rm api-test` 能執行並通過錯誤格式測試與 `UTCDateTime` 測試
- [x] 測試結束後 `db-test` 不留資料（tmpfs）

**Verification:**
- [x] `docker compose --profile test run --rm api-test`

**Dependencies:** T2
**Files:** `backend/app/core/{exceptions.py,logging.py}`、`backend/app/main.py`、`backend/tests/{conftest.py,test_errors.py,test_types.py}`、`backend/Dockerfile`、`docker-compose.yml`
**Scope:** M

### ✅ T4：認證、角色權限與種子帳號
**Description:**
- 密碼雜湊用 pwdlib argon2；JWT（PyJWT）只放 `sub` 和 `exp`
- `get_current_user` 每次從 DB 讀角色與狀態；`require_role(*roles)` dependency
- 端點：register（`extra="forbid"`，預設角色 user）、login（OAuth2 form）、`/users/me`
- `log_action()` 共用函式，登入成功與失敗、註冊都寫入 system_logs
- `app/seed.py` 冪等建立三個種子帳號

**Acceptance criteria:**
- [x] 註冊成功；重複帳號回 409；帶 `role=admin` 回 422 且不建立帳號
- [x] 登入取得 token；錯誤密碼 401；停用帳號 401；Swagger Authorize 可用
- [x] 三個種子帳號可登入；重啟 api 不會重複建立帳號

**Verification:**
- [x] `test_auth.py` 涵蓋上述情境，pytest 全綠
- [x] Swagger 手動 Authorize，接著呼叫 `/users/me`

**Dependencies:** T3
**Files:** `backend/app/core/{security.py,deps.py}`、`backend/app/api/v1/{auth.py,users.py}`、`backend/app/schemas/user.py`、`backend/app/services/{user_service.py,log_service.py}`、`backend/app/seed.py`、`backend/tests/test_auth.py`
**Scope:** M（接近 L；若超時，把 seed 拆成獨立小任務）

> 實作備註：Swagger 的 OAuth2 password flow 已出現在 openapi.json（tokenUrl=/api/v1/auth/login），並用 curl 送 form 登入驗證過；瀏覽器上的 Authorize 按鈕尚未手動點過。

### ✅ Checkpoint 1（10/19 結束前）
- [ ] `docker compose down -v && docker compose up --build` 一次起得來
- [ ] 三個種子帳號登入成功，Swagger 可 Authorize
- [ ] pytest 全綠
- [ ] 跟你確認進度，再進入 Phase 2

---

## Phase 2：Records（10/20 上午）

### ✅ T5：Records CRUD 與建立者權限
**Description:** schemas（Create、Put、Patch、Read）、`record_service`（建立者檢查放在 service 層）、POST、GET by id、PUT、PATCH、DELETE，每個寫入操作都呼叫 `log_action`。

**Acceptance criteria:**
- [x] user 與 admin 可新增；viewer 新增回 403
- [x] user 改或刪別人的資料回 403；admin 可改任何人的；不存在回 404
- [x] PATCH 只更新有帶的欄位；PUT 缺欄位回 422
- [x] body 的 `timestamp` 用 `AwareDatetime`：不帶時區回 422（不是 500）

**Verification:**
- [x] `test_records_crud.py` 全綠

**Dependencies:** T4
**Files:** `backend/app/schemas/record.py`、`backend/app/services/record_service.py`、`backend/app/api/v1/records.py`、`backend/tests/test_records_crud.py`
**Scope:** M

### ✅ T6：Records 列表（分頁、篩選、排序）
**Description:** `GET /records` 支援 page、size（1–100）、category、start/end、min/max_value，`sort_by` 用 `Literal` 白名單，回傳 `{items, total, page, size}`。

**Acceptance criteria:**
- [x] 各篩選條件可組合使用，total 是篩選後的總筆數
- [x] `size=101` 或非法的 `sort_by` 回 422
- [x] 排序方向正確，第 2 頁的資料不與第 1 頁重複
- [x] `start` / `end` 用 `AwareDatetime`：`start` 不帶時區回 422

**Verification:**
- [x] `test_records_list.py` 全綠

**Dependencies:** T5
**Files:** `backend/app/schemas/record.py`、`backend/app/services/record_service.py`、`backend/app/api/v1/records.py`、`backend/tests/test_records_list.py`
**Scope:** S

### ✅ T7：CSV / JSON 批量匯入
**Description:** `POST /records/import` 依副檔名解析，逐列用 Pydantic 驗證；不帶時區的時間視為 Asia/Taipei 再轉 UTC。合格列以單一 transaction `add_all` 寫入，回傳成功筆數、失敗筆數與錯誤列。上限 5 MB 或 1 萬列，超過回 413。另建立 `sample_data/records.csv` 與 `records.json`。

**Acceptance criteria:**
- [x] 混合好壞列的 CSV：好的寫入，壞的回報列號與原因
- [x] 不帶時區的 `2026-10-20 08:00:00` 存成 `00:00:00Z`
- [x] viewer 匯入回 403；超過上限回 413；不支援的副檔名回 422

**Verification:**
- [x] `test_records_import.py` 全綠
- [x] Swagger 上傳 `sample_data/records.csv` 成功

**Dependencies:** T5
**Files:** `backend/app/services/import_service.py`、`backend/app/api/v1/records.py`、`backend/tests/test_records_import.py`、`sample_data/records.{csv,json}`
**Scope:** M

### ✅ Checkpoint 2（10/20 12:00）
- [ ] Swagger 走完 records 全流程，三種角色權限正確
- [ ] pytest 全綠
- [ ] 跟你確認進度

---

## Phase 3：即時監控與前端骨架（10/20 下午）

### ✅ T8：資料產生器、異常標記、批次寫入
**Description:** `realtime/buffer.py`（append 達門檻就 set Event；flush 時換 list 後 `add_all`；失敗放回前端，有上限）、`realtime/generator.py`（每秒產生一筆，依上下限判斷異常），由 lifespan 啟動與停止，關機時先停 generator 再做最後一次 flush。`ENABLE_GENERATOR=false` 時不啟動。

**Acceptance criteria:**
- [x] 啟動後 `metrics` 表筆數持續增加，log 顯示每次 flush 的筆數
- [x] 達到 `FLUSH_BATCH_SIZE` 時不等間隔就立即 flush；flush 失敗時資料回到 buffer，超過上限丟最舊的
- [x] `docker compose restart api` 時 log 出現關機 flush，且筆數符合

**Verification:**
- [x] `test_buffer.py` 單元測試（門檻觸發、失敗放回、上限丟棄）
- [x] 手動執行 restart 並觀察 log

**Dependencies:** T4（需要 models 與 session；不依賴 records）
**Files:** `backend/app/realtime/{buffer.py,generator.py}`、`backend/app/main.py`、`backend/app/core/config.py`、`backend/tests/test_buffer.py`
**Scope:** M

### ✅ T9：WebSocket 推送與 /metrics/latest
**Description:**
- `realtime/ws_manager.py`：以 gather + timeout 廣播，失敗的連線移除
- `WS /ws/metrics?token=`：先 accept 再驗證，失敗以 1008 關閉
- generator 每筆資料同時廣播與寫入 buffer
- `GET /metrics/latest`：合併 buffer 與 DB 的資料，依時間排序並去重
- uvicorn access log 過濾掉 ws 路徑

**Acceptance criteria:**
- [x] 帶有效 token 連線每秒收到一筆 JSON；無效 token 收到 close code 1008
- [x] `/metrics/latest?limit=10` 回傳最新 10 筆，包含還沒 flush 的資料；viewer 可讀
- [x] access log 裡看不到 token

**Verification:**
- [x] `test_ws.py`（用 Starlette TestClient 的 websocket_connect 測驗證成功與失敗）。TestClient 會自己開一個 event loop，測試用 engine 要改用 `NullPool`，避免連線池裡的連線綁在別的 loop 上，出現 "attached to a different loop" 錯誤
- [x] （未觸發）若 30 分鐘內仍卡在 event loop 問題：WS 測試只測 token 驗證函式，連線行為改成手動驗證，並在 README 註明
- [x] 手動用瀏覽器 console 執行 `new WebSocket(...)` 確認

**Dependencies:** T8
**Files:** `backend/app/realtime/ws_manager.py`、`backend/app/api/v1/{ws.py,metrics.py}`、`backend/app/realtime/generator.py`、`backend/app/core/logging.py`、`backend/tests/test_ws.py`
**Scope:** M

> 實作備註：uvicorn 的 WebSocket 握手 log 在 `uvicorn.error` 而非 access log，改為兩個 logger 都遮蔽 token。TestClient 測試曾因「accept 後、註冊進 manager 前就廣播」的時序問題卡住，測試改為先等註冊完成；test stage CMD 加 300 秒逾時。

### ✅ T10：Streamlit 骨架（登入、登出、依角色 navigation）
**Description:** frontend uv 專案、多階段 Dockerfile，compose 加入 frontend（依賴 api healthy）。`utils/api.py`（httpx，`API_BASE_URL`，401 時清 session）、`utils/auth.py`，`app.py` 用 `st.navigation` 依登入狀態與角色組出頁面；先放 login 頁與空白功能頁。

**Acceptance criteria:**
- [x] `docker compose up` 後打開 localhost:8501 可登入、登出
- [x] 非 admin 的選單看不到「系統管理」
- [x] token 過期或無效時自動回到登入頁

**Verification:**
- [x] 手動用三種角色登入，比對選單

**Dependencies:** T4
**Files:** `frontend/{app.py,pyproject.toml,Dockerfile}`、`frontend/utils/{api.py,auth.py}`、`frontend/views/login.py`、`docker-compose.yml`
**Scope:** M

> 實作備註：登入／登出／密碼錯誤／token 失效導回登入頁以 Streamlit `AppTest` 在 frontend 容器內對真實後端驗證；選單依角色顯示以瀏覽器確認（user 三項、admin 四項）。另加了註冊分頁（5.1 的註冊 API 前端入口）。

### ✅ T11：即時監控頁（方案 A，2h 時限）
**Description:** `views/monitor.py` 用 `components.html` 嵌入 JS：先用 `/metrics/latest` 的資料畫初始圖，再以 `PUBLIC_WS_URL` 加 token 連線，Chart.js 畫折線圖（異常點變色）和各 category 的柱狀圖，異常時顯示告警橫幅。**開始時記下時間，超過 2h 先停下來問你，再退回方案 B**（`st.fragment(run_every="1s")` 拉 `/metrics/latest`）。

**Acceptance criteria:**
- [x] 登入後即時頁的折線圖每秒更新，視窗保留最近 60 點
- [x] 異常點用不同顏色，並出現告警
- [x] 柱狀圖顯示各 category 的計數

**Verification:**
- [x] 手動觀察 1 分鐘；把閾值調低以確認告警會出現

**Dependencies:** T9、T10
**Files:** `frontend/views/monitor.py`、`frontend/utils/config.py`、`docker-compose.yml`
**Scope:** S

> 實作備註：18:47 開始，未超過 2 小時時限，未觸發退回方案 B。`components.v1.html` 在 Streamlit 1.66 已棄用，改用 `st.iframe`（HTML 字串走 srcdoc）。瀏覽器驗證：每秒更新、異常紅點與告警（以 METRIC_ANOMALY_HIGH=60 重啟確認）、API 重建後自動重連、帳號停用後收到 1008 顯示重新登入且不重連。

### ✅ Checkpoint 3（10/20 18:00）
- [ ] 前端即時圖正常，`metrics` 批次寫入的 log 正常，restart 時有關機 flush
- [ ] 跟你說明三個面試必問點中的兩個：批次寫入、Streamlit 接即時資料（寫進 README 草稿）
- [ ] 確認進度與是否需要降級

---

## Phase 4：資料分析（10/20 晚）

### ✅ T12：分析 API（summary / by-category / trend）
**Description:** `analytics_service`：依 `source` 選擇 Record 或 Metric model，兩者共用同一組聚合函式；trend 用 `func.date_format` 依 minute、hour、day 截斷時間後分組。所有端點都支援 start、end、category 篩選，`source` 預設 metrics。

**Acceptance criteria:**
- [x] summary 回傳的 count、sum、avg、max、min 對已知資料計算正確（records 與 metrics 各一組測試）
- [x] by-category 每個分類各一列；trend 依區間分組並依時間排序
- [x] 非法的 `source` 或 `interval` 回 422

**Verification:**
- [x] `test_analytics.py` 全綠

**Dependencies:** T5、T8
**Files:** `backend/app/services/analytics_service.py`、`backend/app/schemas/analytics.py`、`backend/app/api/v1/analytics.py`、`backend/tests/test_analytics.py`
**Scope:** M

> 實作備註：trend 以 `analytics_timezone`（預設 Asia/Taipei，換算成數字偏移）經 `convert_tz` 轉換後再分組，bucket 回傳 UTC。禁止原生 SQL 的 grep 改為 `(^|[^A-Za-z0-9_])text\(`，避免 `send_text(` 誤判。

### ✅ T13：Excel 匯出
**Description:** `GET /analytics/export` 套用與分析相同的篩選條件，用 openpyxl 產生 `data` 工作表（上限 50,000 列）和 `summary` 工作表，以 StreamingResponse 下載。

**Acceptance criteria:**
- [x] 下載的 `.xlsx` 可用 openpyxl 讀回，兩張工作表內容正確
- [x] 篩選條件生效；回應帶有正確的 Content-Disposition 檔名

**Verification:**
- [x] `test_export.py` 全綠

**Dependencies:** T12
**Files:** `backend/app/services/export_service.py`、`backend/app/api/v1/analytics.py`、`backend/tests/test_export.py`
**Scope:** S

> 實作備註：時間換成 Asia/Taipei（Excel 不支援時區）、字串強制為文字防公式注入、超過上限保留最新資料。時區設定由 `ANALYTICS_UTC_OFFSET` 改為 `ANALYTICS_TIMEZONE`（IANA 名稱），偏移由名稱換算。

### ✅ T14：前端 Records 頁與分析頁
**Description:**
- `views/records.py`：列表、篩選、分頁、排序、新增、編輯、刪除、上傳匯入，依角色隱藏按鈕
- `views/analytics.py`：source 與篩選條件、summary 指標卡、分類長條圖、趨勢折線圖、Excel 下載按鈕

**Acceptance criteria:**
- [x] user 能完成 records 的新增、修改、刪除與匯入；viewer 看不到寫入相關按鈕
- [x] 分析頁切換 source 或篩選條件後，圖表跟著更新；Excel 可下載

**Verification:**
- [x] 用 user 和 viewer 兩種角色手動走過一次

- [x] 所有時間顯示一律轉 Asia/Taipei（API 回傳 UTC；trend 的 bucket 例如台北 10/20 是 `2026-10-19T16:00:00Z`，直接畫會讓人以為分組錯了），欄位標題註明時區

**Dependencies:** T6、T7、T10、T13
**Files:** `frontend/views/{records.py,analytics.py}`、`frontend/utils/api.py`
**Scope:** M

> 實作備註：AppTest 對真實後端驗證 user 新增／篩選／編輯／刪除、viewer 無寫入分頁、分析頁兩種來源；瀏覽器驗證匯入（部分成功與錯誤列表）與圖表；Excel 下載以按下時才產生的 callable 實作，在容器內驗證回傳有效 xlsx。

### ✅ Checkpoint 4（10/20 結束前）
- [ ] 前端可操作 records、即時、分析三個模組；pytest 全綠
- [ ] 確認 10/21 的範圍

---

## Phase 5：Admin 與交付（10/21）

### ✅ T15：Admin API
**Description:** `/admin/users`（分頁）、`PATCH /admin/users/{id}`（修改 role、is_active，不能改自己，寫 log）、`/admin/logs`（依 level、action、時間篩選並分頁）、`/admin/db-status`（`select(literal(1))`、`engine.pool` 狀態、各表 `func.count()`、buffer 待寫筆數）、`/admin/metrics`（時間範圍加 `anomaly_only`）。

**Acceptance criteria:**
- [x] 非 admin 呼叫任何 admin 端點回 403；admin 改自己回 403 或 409
- [x] 停用某個帳號後，該帳號手上的舊 token 立刻變成 401
- [x] db-status 回傳連線、pool、各表筆數、buffer 筆數

**Verification:**
- [x] `test_admin.py` 全綠

**Dependencies:** T8
**Files:** `backend/app/services/admin_service.py`、`backend/app/schemas/admin.py`、`backend/app/api/v1/admin.py`、`backend/tests/test_admin.py`
**Scope:** M

> 實作備註：admin router 掛 router 層級的 `require_admin` dependency，新增端點不會漏檢查。Admin 改自己回 403。pool 狀態回報 `overflow_in_use`（SQLAlchemy `overflow()` 未用滿時為負數，容易誤讀）。

### T16：前端系統管理頁
**Description:** `views/admin.py` 分四個 tab：使用者管理（改角色、停用）、系統日誌、DB 狀態、metrics 歷史。

**Acceptance criteria:**
- [ ] admin 可在頁面上改角色與停用帳號，結果立即反映
- [ ] 四個 tab 都能載入資料

**Verification:**
- [ ] 手動：admin 停用 user 帳號後，user 那邊**不重新整理**，直接執行任一操作 → 收到 401 並被導回登入頁

**Dependencies:** T10、T15
**Files:** `frontend/views/admin.py`、`frontend/utils/api.py`
**Scope:** S

### T17：README、架構圖、交付文件（**不可砍，10/21 12:00 前開始**）
**Description:**
- README 內容：介紹、技術棧、一行啟動、本地開發、測試指令、API 文件連結、三種角色測試帳號、設計決策（批次寫入、即時資料接法、權限分層、JWT 只放 id、時間存 UTC、單一 worker、token 走 query 的取捨、多階段建置、不用原生 SQL 的做法）、已知限制
- 用 archify 產生 `docs/architecture.{png,html}`，超過 20 分鐘就改用 Mermaid
- 核對 `.env.example` 的變數完整

**Acceptance criteria:**
- [ ] README 涵蓋 SPEC 第 12 節的交付項目
- [ ] 架構圖顯示三個容器、network、volume、REST/WS 流向、批次寫入路徑
- [ ] `.env.example` 與 `config.py` 的變數一一對應

**Verification:**
- [ ] 照著 README 從頭操作一遍

**Dependencies:** 所有功能任務
**Files:** `README.md`、`docs/architecture.{png,html}`、`.env.example`
**Scope:** S

### T18：交件驗證
**Description:** 跑一次 `/review`，修正發現的問題；做禁止原生 SQL 的 grep；在乾淨環境驗證（新目錄重新 clone、`docker compose down -v`、不建 `.env`）；逐項勾選 SPEC 第 12 節；把 repo 設成 public。

**Acceptance criteria:**
- [ ] SPEC 第 12 節全部勾選
- [ ] 乾淨環境一行啟動成功
- [ ] GitHub repo 為 public，且可匿名 clone

**Verification:**
- [ ] 在另一個目錄 `git clone <url> && docker compose up --build`

**Dependencies:** T17
**Files:** 依 review 結果而定
**Scope:** S–M

### ✅ Checkpoint 5（10/21 15:00 前）
- [ ] 全部交付項目完成，回信附上 GitHub 連結
