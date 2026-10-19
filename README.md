# 即時資料分析與監控系統

> 草稿：功能完成後（T17）補齊專案介紹、技術棧、啟動步驟、API 文件、測試帳號與架構圖。

## 設計決策

### 權限檢查分兩層
- **角色**（admin / user / viewer）由 FastAPI dependency `require_role(...)` 檢查：只需要看登入者本身，在進入業務邏輯前就能擋下。
- **「只有建立者或 Admin 能改」** 放在 service 層：必須先把資料讀出來才知道建立者是誰。

### JWT 只放 user id
角色與啟用狀態每次請求都從 DB 讀取。代價是每個請求多一次主鍵查詢；換來的是 Admin 停用帳號或改角色時立即生效，不必等舊 token 過期。

### 登入失敗不洩漏帳號是否存在
帳號不存在與密碼錯誤回傳相同的 401 與訊息；帳號不存在時也會用一個假 hash 跑一次 argon2 驗證，讓兩種情況的回應時間相近，避免以時間差枚舉帳號。

### 時間一律以 UTC 儲存
MariaDB `DATETIME` 不存時區。`UTCDateTime` 型別在寫入時轉 UTC、讀出時補回 UTC，並拒收沒有時區的 datetime。API 的時間參數使用 Pydantic `AwareDatetime`，沒帶時區回 422（在邊界擋下，避免進到 DB 層變成 500）。CSV / JSON 匯入例外：沒帶時區的時間視為 Asia/Taipei。

### 批量匯入採部分成功
逐列驗證，合格列以單一 transaction 一次寫入，不合格列回報資料列序號與原因。上限 5 MB / 10,000 列（超過回 413）。

### 即時資料批次寫入
產生器每秒產生一筆資料，同時交給「WebSocket 廣播」與「記憶體 buffer」；buffer 每 5 秒或累積 50 筆（先到者）整批 `add_all` 寫入 DB。
- 每秒寫一次 DB 等於每秒一個 transaction；累積後整批寫入，大幅減少 commit 次數與連線占用。
- 不用共用 `asyncio.Queue`：Queue 每筆只會被一個消費者取走，廣播與寫入會各拿到約一半資料。
- flush 時先把 buffer 換成新的空 list 再寫入：換的動作沒有 `await`，產生器插不進來；寫入期間的新資料進新 list，不會漏也不會重複。
- 寫入失敗（DB 斷線）時資料放回 buffer 前端，下次重試；失敗後等一個完整間隔才重試，避免狂打 DB。buffer 有上限（預設 1 萬筆），超過丟最舊的，避免記憶體無限成長。
- 關機時依序：停產生器 → 等 flush 迴圈跑完當次（用旗標停止，不用 cancel，以免中斷進行中的 commit）→ 最後一次 flush。
- uvicorn 只能 1 個 worker：多 worker 各自跑一個產生器，資料會重複。
- 失敗放回 buffer 屬於 **at-least-once**：若 commit 其實已在 DB 成功、只是回應送回前連線中斷，程式會判定失敗並重送，造成重複資料。正式環境可為每筆資料產生唯一鍵（例如 UUID）並加 unique constraint，以 `INSERT ... ON DUPLICATE KEY` 類的冪等寫入去重。

### WebSocket 推送
- 瀏覽器原生 WebSocket 無法帶 `Authorization` header，JWT 只能放 query string（`?token=`）。代價是 token 會出現在 uvicorn 的 log：WebSocket 握手記在 `uvicorn.error`（不是 access log）。因此在兩個 logger 都加上 filter，把 `token=...` 遮成 `token=***`。
- 驗證失敗時**先 accept 再以 close code 1008 關閉**：若未 accept 就 close，伺服器只會回 HTTP 403，瀏覽器端拿不到 1008 與原因。
- 廣播以 `asyncio.gather` 並行送出，每條連線設 1 秒逾時；逾時或出錯的連線直接移除。若逐一 `await`，一條慢連線會拖住產生器，所有人的資料都延遲。
- `GET /api/v1/metrics/latest` 合併 DB 與 buffer 中尚未寫入（含寫入中）的資料，前端初次載入或 polling 時不會漏掉最近幾秒。

### Streamlit 如何接即時資料
Streamlit 每次互動都會重跑整份 script，Python 端無法長期維持一條 WebSocket 連線。因此即時監控頁用 `st.iframe` 嵌入一段 HTML／JS，由**瀏覽器**直接連 WebSocket 並以 Chart.js 畫圖，是真正的 push 而非 polling。
- **兩個位址**：Streamlit 的 Python 端在容器內呼叫後端用 `API_BASE_URL=http://api:8000`；iframe 的 JS 在使用者瀏覽器執行，用 `PUBLIC_WS_URL=ws://localhost:8000`。
- **初始資料由 Python 端抓好注入**：iframe 內的 JS 若直接 fetch 後端會被 CORS 擋，所以由 Python 端先呼叫 `/api/v1/metrics/latest` 取最近 60 筆，連同 token 以 `json.dumps` 注入（並轉義 `</`），不用字串拼接。
- **頁面不放會觸發重跑的元件**：重跑會重建 iframe，WebSocket 重連、圖表重畫。
- **斷線處理**：收到 close code 1008（token 無效、過期、帳號停用）顯示「請重新登入」且不重連；其他原因（例如 API 重啟）以 1、2、4… 秒漸增間隔自動重連，最長 30 秒。
- **Chart.js 從 CDN（cdnjs）載入**：瀏覽器需能連外網；離線環境需改為把 `chart.umd.min.js` 放進專案由 Streamlit 提供。

### 資料分析
- records 與 metrics 共用 `value / category / timestamp` 三欄，四個分析端點以 `source` 參數切換，聚合邏輯只寫一份。
- 聚合全部用 ORM 表達式：`func.count / sum / avg / max / min` 與 `group_by`。
- **趨勢依台北時間切分**：資料存 UTC，若直接以 UTC 截斷，「一天」會是台北早上 8 點到隔天 8 點。因此先以 `func.convert_tz(timestamp, '+00:00', '+08:00')` 轉換再以 `func.date_format` 截斷到分／時／日（時區由 `ANALYTICS_TIMEZONE` 設定，換算成數字偏移）。用數字偏移 MariaDB 不需匯入時區資料表；台灣無日光節約，不受偏移固定的影響。回傳的 `bucket` 仍統一為 UTC，與其他 API 一致。

### Excel 匯出
- 套用與分析 API 相同的篩選；`data` 工作表上限 5 萬列，超過時保留**最新**的資料（依時間倒序取再反轉），`summary` 工作表記錄篩選條件、實際匯出列數與統計，可看出是否被截斷。
- **防公式注入**：openpyxl 會把 `=` 開頭的字串寫成公式；使用者匯入的 title 若是 `=HYPERLINK(...)`，下載者開檔時就會被執行。所有字串一律強制存成文字。
- Excel 不支援帶時區的時間，因此換成 `ANALYTICS_TIMEZONE`（預設 Asia/Taipei）後去掉時區，欄位標題註明時區。
- 使用 openpyxl 的 write-only 模式逐列寫入，不在記憶體保留整份工作表物件。

### 禁止原生 SQL
應用程式與測試碼內全部使用 SQLAlchemy ORM 表達式，健康檢查也是 `select(literal(1))`。可用下列指令檢查（`send_text(` 這類方法名不會誤判）：

```bash
grep -rnE "(^|[^A-Za-z0-9_])text\(|exec_driver_sql|execute\([\"']" backend/app backend/tests
```

### 容器
- 多階段 Dockerfile：uv 在 builder 階段建好 venv，runtime 只複製 venv 與原始碼，以非 root 使用者執行。
- entrypoint 最後以 `exec` 啟動 uvicorn，讓它成為 PID 1、收得到 `docker stop` 的 SIGTERM，關機流程才會執行。
- 主 `docker-compose.yml` 不對主機開放 DB port，避免審查者本機已有 MySQL 佔用 3306 時啟動失敗；本機開發用 `docker-compose.dev.yml` 開放。

## 已知限制

- **即時資料在記憶體中最多停留一個 flush 間隔**：程序被強制終止（`kill -9`、OOM）時，buffer 中尚未寫入的資料（最多約 5 秒）會遺失；正常 `docker stop` 會執行關機 flush；但若關機時 DB 正好斷線，關機 flush 會卡在連線重試，可能超過 Docker 預設 10 秒寬限期而被 SIGKILL，遺失範圍與強制終止相同。正式環境若不能遺失，應改寫入持久化的訊息佇列（如 Kafka / Redis Streams）再由消費者寫入 DB。
- **列表採 offset 分頁**：頁數很深時 DB 仍需掃過前面所有列（`OFFSET 100000` 很慢）；資料持續新增時，翻頁之間插入的新資料會讓後面的頁出現重複或遺漏。正式環境可改用 keyset（cursor）分頁：以上一頁最後一筆的 `(timestamp, id)` 作為下一頁的起點。
- **即時頁重連期間的資料不會補回**：API 重啟或網路中斷時，重連前的那幾秒在圖上是空白（資料仍有寫入 DB，可從系統管理的歷史查詢看到）。
- **WebSocket 只在握手時驗證 token**：連線建立後，即使 token 過期或帳號被 Admin 停用，仍會持續收到資料，與 REST「停用立即生效」不一致。正式環境可在 token 的 `exp` 到期時由伺服器主動關閉連線，或定期重查 `is_active` 並關閉已停用帳號的連線。
- **匯入的 5 MB 上限只在應用層檢查**：Starlette 在 handler 執行前就已收完整個上傳（大檔暫存到磁碟），`read(上限 + 1)` 只是避免把超出部分讀進 Python 記憶體，無法限制頻寬與磁碟用量。正式環境應在反向代理（例如 Nginx `client_max_body_size`）或依 `Content-Length` 提前拒絕。
