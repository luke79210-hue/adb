# 架構與 API

```text
瀏覽器（web/index.html）
  ├─ 同來源本機頁面自動配對／遠端前端人工輸入權杖
  ├─ GET /api/state：裝置、任務、版本中繼資料
  ├─ GET /api/screen：PNG 畫面輪詢
  └─ GET /api/logs/stream：fetch NDJSON + X-Ultron-Token
          ↓ 127.0.0.1 + Host / Origin allowlist + bearer token
Python ThreadingHTTPServer（server/app.py）
          ↓ 動作白名單、參數驗證、雙重確認
Service（server/core.py）
  ├─ 模式獨立 SQLite + 程序檔案鎖，避免重複啟動影響任務
  ├─ 任務池：最多 8 個 worker；每台僅一個變更任務
  ├─ Monitor：每 10 秒監控、重連、儲存設備狀態
  ├─ ADB：subprocess argv，沒有任意 shell API
  ├─ Drive：HTTPS API，憑證僅於服務環境
  ├─ SQLite：WAL，連線由 RLock 序列化
  └─ .runtime/{apks,media}：本機實體檔案
```

前端無框架或建置依賴；可單獨作為靜態檔案，但預設由本機服務提供，以避開跨來源與瀏覽器區網連線政策問題。API 保留可拆分邊界，尚未開放 LAN 監聽。

## 請求與安全

除了同來源 `GET /api/session` 外，所有 API 皆須 `X-Ultron-Token`；token 每次服務啟動重新產生，瀏覽器 sessionStorage 保存。Origin 只能是本機頁面或人工配置的 HTTPS origin。Host 只能是實際監聽埠的 localhost/127.0.0.1。

每個操作事件記錄來源 IP 與 token 的 SHA-256 短指紋，不記錄 token 明文。第一版只有一個本機 session；不代表多使用者登入系統。

### 主要端點

| Method | Path | 行為 |
| --- | --- | --- |
| GET | `/api/session` | 同來源本機頁面取得權杖；遠端 origin 無法讀取 |
| GET | `/api/state` | 模式、裝置、最近 200 筆任務、APK、package |
| POST | `/api/connect` | `{ip: "192.168.1.101:5555"}` |
| POST | `/api/discover` | `{cidr: "192.168.1.0/24"}`，上限 /24 |
| POST | `/api/device` | `{id, name?, brand?, store?, autoReconnect?}` |
| POST | `/api/refresh` | `{id?}`，未指定則刷新全部 |
| POST | `/api/confirm` | 驗證風險操作，回傳單次 challenge、phrase、warning |
| POST | `/api/tasks` | `{action,devices,params,challenge?,phrase?}` |
| POST | `/api/cancel` | `{id,batch?:boolean}`，id 為任務或批次 ID |
| GET | `/api/screen?device=...` | 真實設備 PNG，模擬模式 409 |
| GET | `/api/screenshot?device=...` | 保存並下載自動命名 PNG |
| GET | `/api/logs?device=...` | 模擬日誌或真實緩衝區快照 |
| GET | `/api/logs/stream?device=...` | 真實 ADB NDJSON；45 秒輪替，前端重連 |
| GET | `/api/file?name=...` | 已生成媒體／舊 APK，檔名與副檔名受限 |
| POST | `/api/apks/upload` | APK binary body；`X-Filename` 為 URL encoded 檔名 |
| GET | `/api/drive` | 列出指定公司資料夾，最多 1,000 筆 |
| POST | `/api/drive/upload` | `{id}`，本機 APK ID |
| POST | `/api/drive/download` | `{id}`，Drive ID；檢查公司 parent 後下載並解析 |
| GET | `/api/events` | 最近 2,000 筆事件 |
| GET | `/api/export` | UTF-8 BOM CSV，公式前綴中和 |
| GET | `/api/diagnostics` | 模式、ADB、資料路徑、功能限制等；不顯示憑證 |
| GET | `/api/backup` | 使用 SQLite backup API，輸出獨立 DELETE-journal 快照 |
| POST | `/api/restore/confirm` | 回傳還原雙重確認 challenge 與 phrase |
| POST | `/api/restore?challenge=...&phrase=...` | raw SQLite body；無執行中任務才可還原 |

## 任務協定

`action` 僅限 `key, restart_app, reboot, shutdown, clear_data, factory_reset, set_time, network_time, install, record`。

- `key`：`params.key` 對映固定 Android keycode，所有按鍵均在白名單。
- `set_time`：`params.time` 為含時區 ISO 8601（1990–2100 年）；或明確 `params.syncComputer: true`，在執行當下取 Mac 時間。兩者均不重啟 APP。
- `install`：`params.apk` 為本機 APK ID，`params.allowDowngrade` 必須是布林值，預設 false。APK 路徑不由客戶端提供。
- `record`：固定 30 秒，裝置暫存檔由服務產生，完成後下載及刪除。

風險動作 `reboot, shutdown, clear_data, factory_reset, install` 先經 `/api/confirm`，再將同一份 payload 與回傳 challenge、精確 phrase 送到 `/api/tasks`。憑證綁定來源、參數、設備，120 秒到期，使用即失效。這是本機單人操作防呆，不是對惡意已授權 API 客戶端的第二因素驗證。

每個 batch 為每台設備建立獨立 task，以同一批次 ID 關聯；最多 8 台同時執行。設備已有 queued/running/cancelling 任務時，整次提交回傳 409，不會隱含排入衝突操作。完成部分任務後出現故障不會自動回復或重試其他裝置。

```text
queued → running → succeeded / failed
              └→ cancelling → cancelled
服務中斷 → interrupted → 人工檢查及重新確認後提交新任務
```

取消是盡力而為：終止本機程序不代表設備已還原。重啟／關機的成功訊息僅代表已送出指令，實際電源／開機狀態待重新監控。批次是並行啟動，並非具硬體時鐘同步保證的原子交易。

## 資料與還原

`devices`、`tasks`、`apks` 保存 ID 及 JSON；`events` 保存 UTC 時間、事件、裝置、內容、IP、session。前端依 Asia/Taipei 或瀏覽器本機時區顯示；Device Time 保留設備 UTC 原值以便比較。

還原前保存 `.runtime/pre-restore-<id>.sqlite3`，檢查資料庫 integrity、必要欄位與 JSON 基本結構。僅複製已知表的資料，避免匯入未知 trigger/schema；執行中的舊任務轉 interrupted，不會重送至設備。SQLite 以交易回復資料，失敗 rollback。

監控狀態可跨服務重啟保存；真實設備在重新連線前顯示離線／未知，不使用舊版 connected 狀態宣稱在線。

## 維運限制

這是單 Mac V1 本機服務，不是公開 Internet 服務。Python 標準 HTTP server、記憶體內權杖及執行緒工作池適合目前單人本機範圍。對外或多人部署前，需獨立處理 HTTPS、身分驗證、工作租約、多程序排程、操作審計保存政策與權限，不應只修改 bind 位址。

ADB 指令參考 [Android 官方 ADB 文件](https://developer.android.com/tools/adb)，Drive 操作參考 [官方 files.create](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/create)。實作不宣稱通過設備端相容性驗證。
