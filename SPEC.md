# Spec：即時資料分析與監控系統（緯穎 take-home）

> 截止：**2026/10/21（三）17:00** 前回傳 GitHub 連結。
> 本文件取代 `SPEC_DRAFT.md`，為開發唯一依據。決策變更先改這裡再改程式。

---

## 1. 目標

建一個 `docker compose up` 一行啟動的即時資料分析與監控系統：FastAPI 後端（REST + WebSocket）、MariaDB 持久化、Streamlit 前端。審查重點預期在後端結構、容器化與可執行性，前端以「功能可操作」為標準。

**使用者**：審查者（clone 後一行啟動、用三種角色測試帳號操作）、面試主管（追問設計決策）。

**成功的樣子**：乾淨環境 `git clone` → `docker compose up` → 不建 `.env` 也能跑 → 瀏覽器開前端登入，四個功能模組都能操作；`/docs` 可用 Swagger Authorize 打所有 API。

## 2. 技術棧（題目硬性要求，不可更改）

| 層 | 要求 |
|---|---|
| 後端 | FastAPI、async、Pydantic 驗證、JWT、RESTful CRUD、WebSocket、Swagger、錯誤處理與日誌 |
| 資料庫 | MariaDB **11.7**、SQLAlchemy ORM（**禁止原生 SQL**，含 `text()`）、Alembic、Engine 連接池、asyncmy、即時資料批次寫入 |
| 前端 | Streamlit 多頁面、登入/登出、Session 狀態、即時圖表、串接後端 API |
| 容器 | 多階段 Dockerfile、Docker Compose、容器間網路、Volume 持久化、環境變數管理 |

### 2.1 選定套件

實作時以 `source-driven-development` 對照官方文件確認版本與 API，版本鎖在 `uv.lock`。

| 用途 | 套件 | 備註 |
|---|---|---|
| 語言 | Python 3.12 | |
| 依賴管理 | uv（`pyproject.toml` + `uv.lock`） | 後端、前端各自一份 |
| ORM | SQLAlchemy 2.x async | `mysql+asyncmy://...` |
| Migration | Alembic | `alembic init -t async` |
| 設定 | pydantic-settings | |
| JWT | PyJWT | HS256 |
| 密碼雜湊 | pwdlib[argon2] | **不用 passlib**（停止維護，搭新版 bcrypt 會出錯） |
| Excel | openpyxl | |
| 前端 HTTP | httpx | |
| 即時圖（瀏覽器端） | Chart.js（CDN） | 方案 A |
| 測試 | pytest、pytest-asyncio、httpx `AsyncClient` | |

## 3. 資料模型

所有時間欄位一律存 **UTC**（MariaDB `DATETIME` 不帶時區，混用本地時間會讓趨勢聚合錯位）；API 輸入輸出使用帶時區的 ISO 8601。

| 表 | 欄位 | 索引 |
|---|---|---|
| `users` | id, username（唯一）, hashed_password, role, is_active, created_at | username unique |
| `records`（手動資料） | id, title, value（float）, category, timestamp, created_by（FK users）, created_at, updated_at | (category, timestamp), created_by |
| `metrics`（即時資料） | id, value, category, timestamp, is_anomaly（bool） | timestamp, (is_anomaly, timestamp) |
| `system_logs` | id, level, action, user_id（nullable FK）, detail, created_at | created_at, (level, created_at) |

- `role` 使用 `sqlalchemy.Enum(Role, native_enum=False)`，存成 VARCHAR：原生 ENUM 新增角色需改 schema，且 Alembic autogenerate 不偵測 ENUM 值變更。
- 使用者不實體刪除，只停用，因此 `records.created_by` FK 不需 cascade。
- `records` 與 `metrics` 分兩表：手動資料有建立者與權限問題，即時資料沒有；分開讓權限邏輯與批次寫入互不干擾。兩表共用 `value / category / timestamp` 三欄，分析模組以此共用聚合邏輯。

## 4. 角色與權限

| 操作 | Admin | User | Viewer |
|---|---|---|---|
| 讀取 records / metrics / 分析 / 匯出 | ✔ | ✔ | ✔ |
| 新增 records、批量匯入 | ✔ | ✔ | ✘ |
| 修改 / 刪除 records | 全部 | 僅自己建立的 | ✘ |
| 系統管理模組 | ✔ | ✘ | ✘ |

- 新註冊帳號預設角色 **user**，由 Admin 調整。
- **JWT 只放 `sub`（user id）與 `exp`**；role、is_active 每次請求由 `get_current_user` 從 DB 讀取。理由：停用帳號或改角色要立即生效，不必等舊 token 過期。
- 角色檢查集中在 dependency `require_role(*roles)`；「僅限建立者」需要先查出資料才能判斷，放 service 層。
- Admin 不能停用自己、不能變更自己的角色（避免系統沒有 Admin）。
- 啟動時依環境變數建立三個種子帳號（admin / user / viewer 各一），已存在則跳過（冪等）。README 列出帳密。
- Access token 效期 60 分鐘（環境變數），**不做 refresh token**，過期重新登入。

## 5. 功能需求與驗收條件

### 5.1 使用者管理
- [ ] `POST /api/v1/auth/register`：username 3–32 字元 `[A-Za-z0-9_]`、password ≥ 8 字元；重複帳號回 409
- [ ] Register schema 只有 `username`、`password`，**不含 role**，且 `model_config = ConfigDict(extra="forbid")`（多帶欄位回 422），角色一律由後端設為 user
- [ ] 驗收：註冊時帶 `role=admin` 不會成為 admin（回 422，且不建立帳號）
- [ ] `POST /api/v1/auth/login`：OAuth2 password flow（form），回傳 `{access_token, token_type}`；Swagger 可直接 Authorize
- [ ] `GET /api/v1/users/me`
- [ ] 未登入或 token 無效回 401；已停用帳號回 401；權限不足回 403

### 5.2 資料管理
- [ ] `POST /api/v1/records`、`GET /api/v1/records/{id}`、`PUT /api/v1/records/{id}`（整筆）、`PATCH /api/v1/records/{id}`（部分）、`DELETE /api/v1/records/{id}`
- [ ] `GET /api/v1/records`：
  - 分頁：`page`（≥1）、`size`（1–100，預設 20）
  - 篩選：`category`、`start` / `end`（timestamp）、`min_value` / `max_value`
  - 排序：`sort_by` ∈ `Literal["timestamp","value","created_at","title"]`、`order` ∈ `asc|desc`（白名單，不接受任意欄位名）
  - 回傳 `{items, total, page, size}`
- [ ] `POST /api/v1/records/import`：上傳 CSV 或 JSON（依副檔名判斷），逐列 Pydantic 驗證，**部分成功**：合格列以單一 transaction `add_all` 寫入，不合格列回報。回傳 `{success_count, failed_count, errors: [{row, message}]}`。上限 5 MB / 10,000 列，超過回 413
- [ ] 匯入的 `timestamp` 若不帶時區，視為 **Asia/Taipei** 再轉 UTC 儲存；帶時區則直接轉 UTC
- [ ] 修改 / 刪除僅限建立者或 Admin，否則 403；不存在回 404

### 5.3 即時監控
- [ ] 背景產生器：FastAPI lifespan 啟動的 asyncio task，每秒（`METRIC_INTERVAL_SECONDS`）產生一筆隨機資料（隨機 category）
- [ ] `value > METRIC_ANOMALY_HIGH` 或 `< METRIC_ANOMALY_LOW` 標記 `is_anomaly`
- [ ] `WS /api/v1/ws/metrics?token=<JWT>`：驗證失敗時**先 `accept()` 再以 close code 1008 關閉**（未 accept 就 close，伺服器只會回 HTTP 403，瀏覽器端看不到 1008 與原因）；成功後推送每筆即時資料（JSON）
  - 瀏覽器 WebSocket 無法帶 header，故用 query parameter（FastAPI 官方範例做法）。代價是 token 會出現在 uvicorn log（WebSocket 握手記在 `uvicorn.error`，不在 access log）→ 在 `uvicorn.access` 與 `uvicorn.error` 加 filter 把 `token=...` 遮成 `token=***`，保留連線紀錄，README 說明
- [ ] `GET /api/v1/metrics/latest?limit=N`：最新 N 筆即時資料（所有角色可讀，預設 60、上限 500），供方案 B 與即時頁初次載入使用。資料取自記憶體中尚未寫入的 buffer 加上 DB，確保不漏最近幾秒
- [ ] **批次寫入**：記憶體 buffer，每 `FLUSH_INTERVAL_SECONDS` 秒或累積 `FLUSH_BATCH_SIZE` 筆時整批寫入；關機 flush 剩餘資料（細節見 6.2）
- [ ] 前端即時折線圖 + 柱狀圖（各 category 計數或最新值），異常點不同顏色並顯示告警

### 5.4 資料分析
所有端點接受 `source` ∈ `records|metrics`（預設 `metrics`）、`start` / `end`、`category` 篩選；兩表共用同一套聚合函式。
- [ ] `GET /api/v1/analytics/summary`：count、sum、avg、max、min
- [ ] `GET /api/v1/analytics/by-category`：每個 category 的 count / avg / max / min
- [ ] `GET /api/v1/analytics/trend?interval=minute|hour|day`：依時間區間分組（`func.date_format` 截斷時間）
- [ ] `GET /api/v1/analytics/export`：下載 `.xlsx`，套用同樣篩選；`data` 工作表（上限 50,000 列）＋ `summary` 工作表
- [ ] 聚合全部用 ORM 表達式（`func.count/avg/max/min`、`group_by`），不寫 SQL 字串

### 5.5 系統管理（Admin only）
- [ ] `GET /api/v1/admin/users`：使用者列表（分頁）
- [ ] `PATCH /api/v1/admin/users/{id}`：修改 role / is_active（不可修改自己）
- [ ] `GET /api/v1/admin/logs`：system_logs 查詢，篩選 level / action / 時間，分頁
- [ ] `GET /api/v1/admin/db-status`：連線檢查（`select(literal(1))`，**不可用 `text("SELECT 1")`**）、連接池狀態（size / checked_in / checked_out / overflow）、各表筆數（`select(func.count()).select_from(Model)`）、即時 buffer 待寫筆數
- [ ] `GET /api/v1/admin/metrics`：metrics 歷史查詢，時間範圍 + `anomaly_only`，分頁

### 5.6 非功能
- [ ] 統一錯誤格式 `{"error": {"code", "message", "details"}}`，handler 涵蓋：自訂 `AppError`、`HTTPException`、`RequestValidationError`（422）、未預期例外（500，不洩漏 stack trace）
- [ ] 日誌：stdlib logging 輸出到 stdout（含時間、level、logger、訊息）；重要操作（登入成功/失敗、註冊、records 新增/修改/刪除/匯入、角色變更、停用、flush 失敗）同時寫入 `system_logs`
- [ ] `GET /health`：不需登入，回傳 DB 連線狀態，給 compose healthcheck 用
- [ ] Swagger 在 `/docs`
- [ ] 所有 request 的時間欄位（body 與 query 參數）型別一律用 Pydantic `AwareDatetime`，沒帶時區回 **422**。理由：`UTCDateTime` 在 bind 階段拒收 naive datetime 時丟的 ValueError 會被 SQLAlchemy 包成 `StatementError` 變成 500，使用者輸入錯誤不該是 500，必須在 API 邊界就擋下。例外：CSV / JSON 匯入維持「無時區視為 Asia/Taipei」，由 `import_service` 自行轉換（見 5.2）
- [ ] 所有設定由 pydantic-settings 從環境變數讀取；compose 內所有變數都有開發用預設值（`${VAR:-default}`），**不建 `.env` 也能啟動**；`.env.example` 列出全部變數與說明

## 6. 架構與關鍵設計

### 6.1 Streamlit 接即時資料：方案 A，超時退回 B
Streamlit 每次互動整份 script 重跑，Python 端無法長期維持 WebSocket 連線。
- **A（採用）**：即時監控頁用 `st.components.v1.html` 嵌入 JS，由**瀏覽器**直連 WebSocket、Chart.js 畫圖。真正的 push。
- **B（退路）**：`st.fragment(run_every="1s")` 定時拉 `GET /api/v1/metrics/latest`（所有角色可讀，見 5.3）。本質是 polling。
- **降級規則**：方案 A 這一片超過 2 小時未完成即改 B，README 說明取捨。

**兩個位址**：Streamlit Python 在容器內呼叫後端用 `API_BASE_URL=http://api:8000`；方案 A 的 JS 跑在使用者瀏覽器，用 `PUBLIC_WS_URL=ws://localhost:8000`。

### 6.2 批次寫入
```
generator ──每筆──┬─▶ ws_manager.broadcast()   （gather + timeout，失敗連線移除）
                  └─▶ buffer.append()           （達 BATCH_SIZE → set flush_event）
flush_task：等 flush_event 或 FLUSH_INTERVAL 逾時 → 把 buffer 換成新 list → add_all + commit
lifespan 結束：停 generator → 最後一次 flush
```
- **廣播與 flush 不共用 `asyncio.Queue`**：Queue 每筆只會被一個消費者取走，兩個 task 一起消費會各拿到約一半。
- **廣播不可阻塞產生器**：逐一 `await send` 時，一條慢連線會拖住整個產生器 → 用 `asyncio.gather` 加 `asyncio.wait_for` timeout 並行送出，失敗或逾時的連線移除。
- **換 list 是安全的**：asyncio 單執行緒，「取出舊 list、指派新 list」之間沒有 `await`，不會被產生器插隊。
- **flush 失敗不丟資料**：寫入例外時把該批放回 buffer 前端；buffer 上限 `BUFFER_MAX_SIZE`，超過丟最舊的並寫 log。
- **uvicorn 只能 1 個 worker**：多 worker 各跑一個產生器會重複產生資料（README 註明）。

### 6.3 容器啟動順序
- `db`：MariaDB 11.7，healthcheck `healthcheck.sh --connect --innodb_initialized`，named volume 持久化
- `api`：`depends_on: db: condition: service_healthy`；以 entrypoint 腳本 `backend/entrypoint.sh` 啟動（`set -e` → `alembic upgrade head` → `python -m app.seed` → 最後 `exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`）。用 `exec` 讓 uvicorn 取代 shell 成為 PID 1，`docker compose stop` 送出的 SIGTERM 才會到 uvicorn、觸發 lifespan 結束與關機 flush；若由 shell 當 PID 1，訊號不會轉送，10 秒後被 SIGKILL，buffer 資料遺失
- `api` healthcheck：`python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"`。slim 映像沒有 curl，不為此多裝套件
- `frontend`：`depends_on: api: condition: service_healthy`
- `db-test`：`profiles: [test]`，資料放 tmpfs，只給 pytest 用
- `api-test`：`profiles: [test]`，用 backend Dockerfile 的 `test` stage（builder 之上再裝 dev 依賴），連 `db-test` 執行 `pytest`
- 單一 compose 自訂 network，服務間以服務名互連

### 6.4 「禁止原生 SQL」的邊界
- Alembic migration 使用 `op.create_table` 等 API 可接受
- 應用程式碼與測試碼內任何 `text()`、`exec_driver_sql`、`execute("字串")` 都不允許，包含健康檢查
- 交件前驗證：`grep -rnE "(^|[^A-Za-z0-9_])text\(|exec_driver_sql|execute\([\"']" backend/app backend/tests` 必須無結果

### 6.5 多階段 Dockerfile
- builder：`python:3.12-slim`，以 `COPY --from=ghcr.io/astral-sh/uv:<固定版本> /uv /usr/local/bin/uv` 取得 uv；設 `UV_PYTHON_DOWNLOADS=0`（禁止 uv 自行下載 Python，強制使用映像內的 `/usr/local/bin/python3.12`）；`uv sync --frozen --no-dev` 建 `/app/.venv`
- runtime：`python:3.12-slim`，只複製 `.venv` 與原始碼，非 root 使用者執行
- builder 與 runtime 同一個基底映像，venv 內指向的 Python 路徑才會一致；若 builder 用 uv 下載的 Python，複製到 runtime 後 venv 會找不到直譯器
- `uv.lock` 必須 commit（`--frozen` 依賴它；沒有 lock 會建置失敗）

## 7. 專案結構

```
wiwynn_takehome/
├── backend/
│   ├── app/
│   │   ├── main.py            # app 建立、lifespan（產生器、flush task）、router 掛載
│   │   ├── seed.py            # 種子帳號（冪等）
│   │   ├── core/              # config, security(JWT/hash), logging, exceptions, deps(require_role)
│   │   ├── db/                # engine, session, base
│   │   ├── models/            # SQLAlchemy models
│   │   ├── schemas/           # Pydantic
│   │   ├── api/v1/            # auth, users, records, analytics, admin, ws
│   │   ├── services/          # 業務邏輯、建立者權限檢查、system_logs 寫入
│   │   └── realtime/          # generator, buffer, ws_manager
│   ├── migrations/            # Alembic
│   ├── tests/
│   ├── entrypoint.sh          # migrate → seed → exec uvicorn
│   ├── pyproject.toml / uv.lock
│   └── Dockerfile             # 多階段
├── frontend/
│   ├── app.py                 # st.navigation：依登入狀態與角色決定可見頁面
│   ├── views/                 # login, records, monitor, analytics, admin
│   ├── utils/                 # api client（httpx）, auth/session
│   ├── pyproject.toml / uv.lock
│   └── Dockerfile             # 多階段
├── docs/architecture.png（＋ .html）
├── sample_data/records.csv（＋ records.json）
├── docker-compose.yml
├── .env.example
└── README.md
```

- 前端用 `st.navigation` + `st.Page`，不用 `pages/` 目錄：`pages/` 的頁面所有人都看得到選單，`st.navigation` 才能對非 Admin 隱藏系統管理頁。
- JWT 存在 `st.session_state`；瀏覽器重新整理會清空 session 須重新登入（README 註明，cookie 持久化列為範圍外）。

## 8. Commands

```bash
# 啟動全部（不需 .env）
docker compose up --build

# 重設資料（刪 volume）
docker compose down -v

# 後端測試（啟動 db-test，在 api 映像內跑 pytest）
docker compose --profile test run --rm api-test

# 本地開發（API/前端不經 Docker；db 用 dev override 對主機開 3306）
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d db
cd backend && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload
cd frontend && uv sync && uv run streamlit run app.py

# 新增 migration
cd backend && uv run alembic revision --autogenerate -m "<message>"

# Lint / format
cd backend && uv run ruff check . && uv run ruff format .

# 禁止原生 SQL 檢查
grep -rnE "(^|[^A-Za-z0-9_])text\(|exec_driver_sql|execute\([\"']" backend/app backend/tests
```

服務位址：前端 `http://localhost:8501`、API `http://localhost:8000`、Swagger `http://localhost:8000/docs`。

## 9. Code Style

- ruff（lint + format），行寬 100；全面 type hints
- 命名：模組與函式 snake_case、類別 PascalCase、常數 UPPER_SNAKE
- 分層：router 只做參數解析與回應組裝 → service 做業務邏輯與權限 → ORM model。router 不直接寫查詢
- 錯誤一律 raise `AppError` 子類（`NotFoundError`、`PermissionDeniedError`、`ConflictError`），由全域 handler 轉成統一格式
- 註解只寫「為什麼」，不寫「做什麼」
- FastAPI 依賴一律用 `Annotated[T, Depends(...)]`（官方建議寫法；也避免 ruff B008 對參數預設值呼叫函式的警告），常用的定義成別名：`SessionDep`、`CurrentUser`

```python
# api/v1/records.py
@router.patch("/{record_id}", response_model=RecordRead)
async def patch_record(
    record_id: int,
    payload: RecordPatch,
    session: SessionDep,
    user: Annotated[User, Depends(require_role(Role.ADMIN, Role.USER))],
) -> Record:
    return await record_service.update(session, record_id, payload, actor=user)


# services/record_service.py
async def update(
    session: AsyncSession, record_id: int, payload: RecordPatch, actor: User
) -> Record:
    record = await session.get(Record, record_id)
    if record is None:
        raise NotFoundError("record", record_id)
    # 建立者檢查需要先讀出資料，所以放在 service 而非 dependency
    if actor.role != Role.ADMIN and record.created_by != actor.id:
        raise PermissionDeniedError("only the creator or an admin can modify this record")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(record, field, value)
    await log_action(session, actor, "record.update", f"id={record_id}")
    await session.commit()
    return record
```

## 10. Testing Strategy

- 框架：pytest + pytest-asyncio，httpx `AsyncClient` + `ASGITransport` 打 app
- **資料庫用 MariaDB（`db-test` 容器），不用 SQLite**：trend 用的 `func.date_format` 是 MariaDB 函式，SQLite 沒有，行為也不同
- schema：測試 session 開始時 `Base.metadata.create_all`，每個測試後用 ORM `delete(Model)` 清表
- 測試時關閉背景產生器（設定 `ENABLE_GENERATOR=false`），buffer / flush 邏輯以單元測試直接驗證
- 範圍（輕量，只測關鍵）：
  - 認證：註冊、重複 409、註冊帶 role 回 422、登入、錯誤密碼 401、停用帳號 401
  - 權限：viewer 新增 403、user 改別人資料 403、admin 可改、非 admin 打 admin API 403、admin 不能改自己
  - Records：CRUD、分頁 / 篩選 / 排序、匯入部分成功
  - 批次寫入：達 BATCH_SIZE 觸發 flush、flush 失敗資料放回 buffer
  - 分析：summary 數值正確（records 與 metrics 各一）
- 不測前端；前端以手動走一次 Demo 流程驗證

## 11. Boundaries

- **Always**
  - 每片完成跑 pytest 與 ruff，通過才 commit
  - 所有 DB 存取走 SQLAlchemy ORM 表達式
  - 新增 / 修改 model 一定配 Alembic migration
  - 所有輸入用 Pydantic 驗證；時間存 UTC
  - 新設定同步加進 `.env.example` 與 compose 預設值
  - 每完成一個關鍵設計，用 2–3 句說明「為什麼」並記入 README 設計決策
- **Ask first**
  - 新增本 spec 未列的依賴
  - 偏離本 spec 的資料模型、API 路徑或權限規則
  - 方案 A 退到方案 B
  - 依第 13 節砍功能
- **Never**
  - `text()` 或任何字串 SQL（含健康檢查與測試）
  - commit `.env` 或真實密鑰
  - 使用 passlib
  - uvicorn 多 worker
  - 為了讓測試通過而刪除或 skip 測試

## 12. Success Criteria（交件檢查）

- [ ] 乾淨環境（刪 volume、重新 clone、無 `.env`）`docker compose up --build` 三個服務都 healthy
- [ ] 三個種子帳號可登入，權限行為符合第 4 節表格
- [ ] 第 5 節所有勾選項目可在 Swagger 或前端操作驗證
- [ ] 即時頁可看到每秒更新的折線圖與柱狀圖，異常點變色並告警；`metrics` 表筆數持續增加且以批次寫入（log 可見每次 flush 筆數）
- [ ] `docker compose restart api` 後 log 顯示關機 flush，資料不遺失
- [ ] 已撰寫的測試全綠（`docker compose --profile test run --rm api-test`）
- [ ] 禁止原生 SQL 的 grep 檢查無結果
- [ ] 交付物：GitHub repo（public）、README（介紹、技術棧、本地運行、Docker 部署、API 文件連結、三種角色測試帳號、設計決策）、`.env.example`、`sample_data/records.csv`、`docs/architecture.png`

## 13. 優先序（時間不夠時由下往上砍）

1. `docker compose up` 一次跑起來（DB + API + 前端）
2. 資料模型 + Alembic、JWT + 角色權限
3. Records CRUD + 分頁篩選排序 + 匯入
4. 產生器 + WebSocket + 批次寫入 + 異常標記
5. 分析 API + Excel 匯出
6. Streamlit 各頁面
7. Admin 模組
8. README + 架構圖（**不可砍**，最晚 10/21 中午前開始）
9. 測試：權限與 CRUD 的關鍵 pytest

## 14. 範圍外

- 前端美化、RWD
- CI/CD、雲端部署
- 多 worker / 水平擴展（README 說明限制）
- refresh token
- 瀏覽器重新整理後保留登入狀態（cookie 持久化）

## 15. Open Questions

目前無。
