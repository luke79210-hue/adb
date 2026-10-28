# Ultron ADB QA 管理平台 V1.0

繁體中文、深色／淺色模式、桌面優先響應式網站，搭配 **Mac 本機 Python 服務 + SQLite + Android platform-tools**。專案原始目錄只有空 Git 儲存庫，沒有可沿用的程式碼。

網站採 GitHub Pages 前端 + Mac 本機服務。發布只包含 `web/`；正式發布操作與配對步驟見 [上線說明](docs/DEPLOYMENT.md)。本機 SQLite、APK、媒體與 `.env` 不公開。

## 快速啟動

需要 Python **3.11 以上**。前端使用原生 HTML/CSS/JavaScript；服務只使用 Python 標準函式庫，無須 npm install 或 pip install。

```sh
cd ultron-adb-qa-site
python3 -m server.app --mode mock
```

模擬資料庫為 `.runtime/ultron-mock.sqlite3`，真實資料庫為 `.runtime/ultron.sqlite3`，兩者隔離，切換模式不覆寫真實設備與任務。

開啟 [本機網站](http://127.0.0.1:8765)。模擬模式有 3 台 STB、模擬 APK、Logcat 與多裝置任務。頁面與每筆任務皆標示模擬。截圖另存可匯出附有「模擬預覽／非真實設備截圖」水印及 MOCK 檔名的展示 PNG；不會將它當作真實 ADB 畫面，也不會產生假錄影或假 Drive 上傳成功。

若 8765 埠已使用，可加入 `--port 8766`。不同埠的資料仍預設保存於 `.runtime/`；同一份資料庫只應由一個服務程序使用。

## 真實 ADB 模式

1. 安裝 Google 官方 [Android platform-tools](https://developer.android.com/tools/releases/platform-tools)。
2. 依 `.env.example` 建立本機 `.env`，設定**真正的奧創 Package Name**、ADB 絕對路徑。預設 `com.ultron.app` 僅是可設定的佔位值，並未確認是公司的真實 Package Name。
3. 設備啟用 ADB，允許本 Mac 的 RSA 金鑰；Android 無線除錯配對碼流程需先在終端執行 `adb pair IP:PORT`。前端提供傳統 IP/Port 連線。
4. 停止模擬服務，再啟動真實模式：

```sh
chmod 600 .env
scripts/run-service.sh python3 real
```

或自行傳入環境變數（直接 `python3 -m server.app` 不會讀取 `.env`）：

```sh
ULTRON_PACKAGE=com.company.actualapp ADB_PATH=/opt/homebrew/bin/adb python3 -m server.app --mode real
```

預設僅接受 RFC1918 LAN IPv4；手動連接埠可指定，預設 5555。LAN 搜尋限 /24 或較小網段，僅探測 5555，不會自動遍歷所有網卡或掃描公網。USB 裝置匯入與 `adb pair` 圖形流程尚未實作。

## 已實作範圍

| 模組 | 功能與實際行為 |
| --- | --- |
| 裝置資訊 | 手動 IP/Port 連線、指定 LAN 搜尋、自動重連／手動刷新；STB + IP 最後一段預設名稱；自訂名稱、品牌、店家；ADB/APP 分別顯示；版本、硬體、DeviceID、時間及資源讀取 |
| 監控 | 服務每 10 秒監測；斷線重連與資源 ≥90% 異常寫入 SQLite；前端顯示歷史及最近活動 |
| 遙控器 | 全部指定按鍵、滑鼠及鍵盤快捷鍵；同一批所有選取設備各自並行執行，不限第一台 |
| 畫面 | 真實 ADB `exec-out screencap -p` PNG 約 1.5 秒輪詢、單／多畫面、全螢幕、截圖下載與本機保存；這不是 scrcpy/H.264 低延遲串流，不含音訊 |
| 錄影 | 每台 `screenrecord --time-limit 30`，完成後 pull 回 Mac，自動命名；任務完成可另存。編碼／DRM 限制由設備回報，模擬模式會明確拒絕 |
| Logcat | 真實模式 `logcat -b all -v threadtime` 透過受權杖保護的 NDJSON 即時串流；初始最近 800 行、45 秒輪替重連；搜尋、精確等級、奧創 PID 篩選、暫停捲動、清空畫面、文字匯出 |
| ADB 操作 | APP force-stop + 啟動後 PID 驗證、重啟、關機、清除資料；高風險操作需先檢查選取設備，再輸入指定文字，伺服器驗證單次有效憑證 |
| Device Time | 1990–2100 年含時區、精確到秒、自訂／同步 Mac／恢復自動時間、批次設定與差距比較；設定前需 root，寫入後讀回驗證；**不會重啟 APP** |
| 任務 | 每台狀態、階段進度、結果；單台／批次取消；失敗、取消及中斷後人工重試；設備忙碌回傳 409，要求人工處理；服務重啟不自動重送任務 |
| APK | 本機上傳、解析 Android binary/plain XML Manifest、Package/VersionCode/VersionName、大小、時間及 SHA-256；不接受任意副檔名或無效 APK |
| 安裝與回復 | 每台記錄舊版、備份舊 APK（含 splits）、安裝前再次比對版本、手動允許降版及雙重確認；安裝後驗證版本、APP PID，保存近期異常 Logcat 供人工檢查；可選歷史版人工回復 |
| Google Drive | 公司資料夾列出、真實 APK 上傳、下載至本機重新解析；服務使用環境中的 OAuth access token；下載會驗證 parent 資料夾、類型及大小 |
| SQLite | 裝置、操作、異常、任務及 APK 中繼資料；手動備份／雙重確認還原；還原前另存安全快照；完整性檢查及只匯入已知 schema 的資料 |
| 維運 | 來源 IP / 非機密 Session fingerprint 稽核、系統診斷、CSV 匯出（避免公式注入）；Mac launchd 管理腳本 |

百分比是**工作階段進度**，不是 ADB 安裝工具未提供的精確位元組進度。取消只會停止待執行步驟與本機 ADB 程序；已送出的裝置操作無法撤回，設備端錄影可能持續至 30 秒上限。

## 未完成、未支援與待真機驗證

- **沒有真實 ADB 設備、公司 APK 與 Google 憑證**；真實硬體、版本相容性與公司 Drive 端到端結果尚未驗證。測試採模擬服務與假 ADB adapter，不代表硬體驗證。
- **原廠重置**：真實模式明確回報不支援，未送出廠商未驗證的 reset 廣播或 root 指令。
- **Public IP**：目前標示待驗證，沒有把 Mac 的外網 IP 當作設備 IP。
- **時間**：非 root 設備拒絕變更；部分 root ROM 的 `date` 語法、1990/2100 年支援仍待驗證。失敗可能已關閉自動校時，須人工檢查並恢復。啟用網路時間只能確認設定值，實際 NTP 校時仍待設備驗證。
- **即時畫面**：目前 PNG 輪詢；scrcpy/H.264、音訊與低延遲影片串流未實作。受保護內容可能黑畫面。
- **Logcat**：前端最多保留 3,000 行，非永久完整日誌庫。首次開啟前與斷線期間的全部日誌不保證保存；APP PID 在每次串流重新連線時解析。Android 權限可能限制可讀 buffers。
- **APK**：不包含簽章信任鏈驗證、惡意程式掃描、ABI/minSDK 預檢及 APK split 安裝；Android 安裝器負責最終相容性驗證。資源參照形式的 VersionName 可能顯示數字資源 ID，尚無 resources.arsc 解析。
- **版本回復**：APP 私有資料無法備份；同簽章與 Android 降版限制可能使回復失敗。不會自動解除安裝或刪資料來繞過降版保護。split 舊版雖逐一保存，回復尚需人工處理。異常 Logcat 為關鍵字擷取，需人工判讀，不保證 APP 無異常。
- **Drive**：沒有內建 OAuth 登入／refresh-token 更新精靈；access token 過期需人工更新並重啟服務。單次列出最多 1,000 筆，UI 明確提示後續分頁未載入；上傳為單次 multipart，沒有斷點續傳。其他來源既存 APK 的中繼資料需下載後解析。
- **備份**：SQLite 不包含 APK／媒體實體檔案，須另外備份 `.runtime/apks/` 與 `.runtime/media/`。還原不會補回遺失的實體檔案。
- **同 LAN 多電腦**：前後端 API 已分離，但目前故意只綁定本機；未提供 LAN 公開監聽、帳號、角色或多人權限。未測試／啟用 GitHub Pages 與 loopback 的瀏覽器相容性。
- LaunchAgent 腳本已提供並做語法檢查，**尚未安裝到使用者登入環境**；使用者可用下列指令啟用。

## Google Drive 設定

在 `.env` 設定：

```sh
GOOGLE_DRIVE_FOLDER_ID=your-company-folder-id
GOOGLE_DRIVE_ACCESS_TOKEN=your-oauth-access-token
```

由公司 OAuth 專案啟用 Drive API，token 須可存取指定資料夾並具有讀寫權限。`drive.file` 限於該 OAuth 應用已獲授權的檔案；資料夾、共用雲端硬碟與組織政策可能需要額外管理員設定。憑證只放本機環境，不放前端或 Git。

上傳先存入本機版本庫，按「保存至 Drive」才會寫入遠端。缺憑證、權限不足、token 過期均回報錯誤。API 依 [Google Drive 官方上傳文件](https://developers.google.com/workspace/drive/api/guides/manage-uploads) 與 [共用雲端硬碟支援](https://developers.google.com/workspace/drive/api/guides/enable-shareddrives) 實作。

## Mac 登入啟動與手動維運

先停止手動啟動的服務，避免埠衝突。下列指令會明確安裝／管理使用者的 LaunchAgent：

```sh
scripts/service.sh install mock  # 真實模式改為 real
scripts/service.sh status
scripts/service.sh restart
scripts/service.sh stop
scripts/service.sh start
scripts/service.sh uninstall    # 停止並改名 plist，保留資料
```

登入啟動讀取 `.env`；固定使用安裝時的 Python 絕對路徑。登入服務安裝於 `~/Library/Application Support/Ultron ADB QA/app/`，SQLite、媒體與日誌位於同層 `data/`；首次安裝會遷移專案的 `.runtime/`。變更專案程式或 `.env` 後需重新執行 install，更新服務副本；資料會保留。環境換機或 Python 路徑變動需重新安裝 plist。停止後不會因 KeepAlive 自動重啟，因為 stop 使用 bootout；start 會重新 bootstrap。

## 安全界線

- 僅監聽 `127.0.0.1`，驗證 Host、來源 Origin 與每次啟動產生的隨機權杖；防止未授權遠端控制與 DNS rebinding。
- 同來源本機頁面可取得權杖，遠端前端必須人工配對；權杖只保存在瀏覽器分頁 sessionStorage。信任邊界是目前 Mac 的 OS 使用者與被允許的前端，不防範已能執行本機程式的惡意程式。
- 沒有任意 shell API、不使用 `shell=True`；動作、按鍵、套件名稱、IP、下載檔名皆驗證；ADB 參數由服務白名單建立。
- 不會從前端執行 launchctl 或自行重啟本機服務。高風險任務憑證綁定動作、參數、設備與 session，120 秒到期且只能使用一次。
- 本機資料以受限目錄及 umask 077 建立；`.runtime/`、`.env` 均忽略 Git。APKs、日誌及備份可能含內部資料，請由 Mac 磁碟保護。
- 靜態 `web/` 可作未來 GitHub Pages 前端，但已提供明確觸發的 GitHub Pages 發布流程（一般程式碼提交不會自動發布）。部署時需設定精確 `ULTRON_ALLOWED_ORIGINS=https://luke79210-hue.github.io`，並人工貼上本機權杖；瀏覽器 Local Network Access / mixed-content 政策仍需實際驗證。請勿直接對外開放 8765 埠。

## 測試

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile server/*.py
node --check web/app.js
node --test tests/*.test.js
zsh -n scripts/run-service.sh scripts/service.sh
```

HTTP 整合測試會在 loopback 的臨時埠啟動服務；測試資料與假 ADB 執行檔位於暫存目錄，不連真實設備／Google Drive、不執行 launchctl。

完整結果見 [測試與交付紀錄](docs/VALIDATION.md)，架構與 API 見 [架構說明](docs/ARCHITECTURE.md)。

## 檔案結構

```text
ultron-adb-qa-site/
├── web/
│   ├── index.html           # 三頁式網站入口
│   ├── style.css            # 深淺色、響應式版面
│   ├── app.js               # 裝置、遙控、串流、任務與 APK UI
│   ├── screenshots.js       # 截圖預覽、模擬標示與 PNG 匯出
│   └── time-picker.js       # 行事曆與不循環的時／分／秒選擇器
├── server/
│   ├── app.py               # HTTP API、來源驗證、靜態網站、串流
│   ├── core.py              # ADB、SQLite、任務、備份與 Drive
│   └── apk.py               # binary/plain AndroidManifest 解析
├── scripts/
│   ├── run-service.sh       # .env 載入與服務啟動
│   └── service.sh           # Mac launchd 安裝及維運
├── tests/test_service.py    # 單元與 HTTP／假 ADB 整合測試
├── docs/
│   ├── ARCHITECTURE.md
│   └── VALIDATION.md
├── .env.example
└── .runtime/                # 執行後產生、Git 忽略
    ├── ultron.sqlite3       # 真實資料
    ├── ultron-mock.sqlite3  # 模擬資料
    ├── apks/
    └── media/
```
