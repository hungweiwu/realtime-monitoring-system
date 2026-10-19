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
逐列驗證，合格列以單一 transaction 一次寫入，不合格列回報資料列序號與原因。上限 5 MB / 10,000 列。

### 禁止原生 SQL
應用程式與測試碼內全部使用 SQLAlchemy ORM 表達式，健康檢查也是 `select(literal(1))`。

### 容器
- 多階段 Dockerfile：uv 在 builder 階段建好 venv，runtime 只複製 venv 與原始碼，以非 root 使用者執行。
- entrypoint 最後以 `exec` 啟動 uvicorn，讓它成為 PID 1、收得到 `docker stop` 的 SIGTERM，關機流程才會執行。
- 主 `docker-compose.yml` 不對主機開放 DB port，避免審查者本機已有 MySQL 佔用 3306 時啟動失敗；本機開發用 `docker-compose.dev.yml` 開放。

## 已知限制

- **列表採 offset 分頁**：頁數很深時 DB 仍需掃過前面所有列（`OFFSET 100000` 很慢）；資料持續新增時，翻頁之間插入的新資料會讓後面的頁出現重複或遺漏。正式環境可改用 keyset（cursor）分頁：以上一頁最後一筆的 `(timestamp, id)` 作為下一頁的起點。
