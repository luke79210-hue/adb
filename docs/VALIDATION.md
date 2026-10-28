# 測試與交付紀錄

驗證日期：2026-10-27（Asia/Taipei）。本次從空 Git 儲存庫建立，未連到正式網站、未 Git push、未部署。

## 自動測試

最終完整測試：

```text
python3 -m unittest discover -s tests -v
Ran 27 tests in 12.856s
OK
```

測試覆蓋：

- RFC1918 endpoint 驗證、拒絕公網／loopback／無效埠／指令注入格式。
- API 未授權 401、未授權 Origin 與 Host 403、無任意 shell 路由。
- 真實 HTTP 靜態網站、session、state、任務建立／批次取消與 SQLite 下載。
- 三台設備全部建立獨立任務、衝突回傳 409、單台／整批取消。
- 風險確認綁定 payload/session，且單次有效；錯誤 session 或設備無法重用。
- 手動降版需明確布林允許、再雙重確認；字串 `"false"` 不會誤當成允許。
- 時間上下界／含時區檢查；模擬時間設定與同步電腦時間不重啟 APP。
- 真實 adapter 的非 root 時間設定在送出變更前拒絕。
- 真實模式原廠重置明確回報不支援，沒有送出未驗證 reset 指令。
- APK plain XML 及 binary XML 解析、SHA-256、壞檔拒絕。
- 假 ADB adapter 的安裝流程：記錄舊版、保存舊 APK、安裝後版本／PID／Logcat 驗證、不隱含 `-d`。
- 真正啟動假 ADB 執行檔，驗證 subprocess argv、Logcat NDJSON 資料生成與程序清理。
- Google Drive 下載 parent 資料夾限制（stub HTTP，不連公司雲端）。
- SQLite 完整性、備份／還原、HTTP 雙重確認、還原前安全快照。
- 服務中斷後標記 interrupted；不自動重送。
- 模擬／真實資料庫隔離，重複程序鎖不會誤標記既有執行中任務。
- 模擬模式不假裝錄影／Drive 成功，CSV 危險公式前綴中和。

靜態與語法檢查全部通過：

```text
python3 -m py_compile server/*.py
node --check web/app.js
zsh -n scripts/run-service.sh scripts/service.sh
```

## 瀏覽器驗證

使用 Codex 內建瀏覽器實際操作 `http://127.0.0.1:8765`，驗證：

1. 三頁導覽與 API session 自動配對。
2. 裝置列表、連線／APP 獨立狀態、資源概況與模擬標示。
3. 選取三台設備、點擊遙控 OK，三筆任務皆完成並標示模擬。
4. 重啟設備先檢查選取清單，再輸入 `確認 3 台 reboot`，建立三筆模擬任務。
5. APK 安裝選取三台、安裝前說明與文字雙重確認，三筆安裝均顯示模擬完成。
6. 缺少 Google Drive 憑證時顯示錯誤，不顯示假檔案或上傳成功。
7. 深色／淺色切換、Logcat 資料持續出現。
8. 最終新版服務重新啟動，頁面與三台模擬設備正常載入。

預覽截圖：[preview.png](preview.png)。內建瀏覽器以窄／中等寬度顯示，已目視驗證響應式版面；完整桌面寬度的瀏覽器視覺 QA 尚未執行，不宣稱已涵蓋所有螢幕尺寸。

## 驗證界線

- 本機沒有 adb、真實設備、公司 APK 或 Google 憑證，**沒有真機或公司 Drive 端到端驗證**。
- 所謂真實 adapter 測試是以假執行檔或 stub 覆蓋指令生成與失敗行為，不代表 Android 裝置相容性。
- LaunchAgent 腳本通過語法檢查，但未執行安裝、重啟、停止使用者登入服務。
- GitHub Pages 與 loopback 跨來源及瀏覽器權限流程尚未部署／驗證。
- 不支援項目與後續工作詳列於 README「未完成、未支援與待真機驗證」。

## 交付狀態

所有原始碼、文件與測試均留於目前專案，未建立提交或推送。預覽用臨時服務在驗證後停止；使用者可用 README 的指令重新啟動。模擬資料與開發期間的歷史快照只在 Git 忽略的 `.runtime/` 內，不影響正式站台。


## 後續修正：截圖另存

2026-10-27：原本模擬模式截圖 API 回傳 409，前端僅顯示 toast，沒有可另存的圖片。現在前端在模擬模式匯出附「模擬預覽／非真實設備截圖」水印及 MOCK 檔名的 PNG，不會呼叫真實設備截圖 API。真實模式保留 ADB 擷取與 Mac 本機保存；兩者均顯示圖片預覽及使用者直接點擊的「下載 PNG」連結。有 File System Access API 的瀏覽器另提供位置選擇；不支援時可用圖片右鍵另存。

- 6 項 Node 截圖測試通過：模擬水印與不呼叫 ADB、真實 API 與檔名、單台失敗不阻擋整批、離線／空選取、PNG 驗證、安全檔名。
- 3 項 HTTP 截圖測試通過：以 stub ADB 驗證原始 PNG／下載檔名／本機保存、壞圖片不保存、模擬 API 不假冒真實設備截圖。
- 5 項既有日期時間選擇器測試通過；前端 JavaScript 語法檢查通過。
- 本次未進行瀏覽器實際下載或真實 ADB 設備驗證；測試不代表已驗證瀏覽器下載權限或真機。
- 本機服務維持運行，前端修改重新整理即可載入；未部署正式站台。


## GitHub Pages 上線準備（2026-10-28）

使用者已明確授權發布至 `luke79210-hue/adb`。新增只發佈 `web/` 的工作流程與發布檔案檢查；GitHub Pages origin 已在 Mac 的私有 `.env` 設定，瀏覽器需人工配對本機權杖。

- 35 項 Python 完整測試通過；另新增的 Pages origin 跨來源配對測試通過（共 36 項）。
- 11 項 Node 測試與前端語法檢查通過。
- 確認 Pages 來源可用正確 token 讀取狀態、無 token 回應 401、無法跨來源取得 `/api/session`，以及 preflight 正確。
- 靜態發布檢查通過：僅 6 個前端檔案，未包含 SQLite、APK、媒體、認證及本機環境檔。
- 此段紀錄代表上線前驗證；實際發布須另以 GitHub deployment 成功及正式 URL 回應確認。


### Mac 常駐安裝修正

實際安裝時發現 launchd 無法開啟 Documents 內的啟動腳本；已改為安裝副本至 `~/Library/Application Support/Ultron ADB QA/app/`，資料位於同層 `data/`，不更改 macOS 安全設定。安裝測試確認 SQLite WAL 交易可正確遷移、重新安裝保留原資料、設定檔權限為 0600。

已實際確認 Python 服務監聽 127.0.0.1:8765；以正式 Pages origin 和記憶體內權杖呼叫 API 成功，CORS 回應正確。當前模式為 mock、3 台模擬裝置、ADB 尚未安裝。LaunchAgent 由 launchd 維持，不依賴本次聊天程序。
