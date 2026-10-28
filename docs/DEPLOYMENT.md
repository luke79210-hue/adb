# GitHub Pages + Mac 本機服務

目標儲存庫：`luke79210-hue/adb`。預期網站位址為 `https://luke79210-hue.github.io/adb/`；只有 GitHub Pages deployment 成功後才代表已發布，程式碼提交或本機測試通過不代表上線。

## 發布流程

1. 儲存庫 Settings → Pages → Build and deployment → Source 選 **GitHub Actions**。
2. 執行 **Publish Ultron QA to GitHub Pages** 工作流程；或在已授權正式發布時，新增／更新 `.github/pages-release.json` 觸發一次發布。普通程式碼提交不會自動部署。
3. 工作流程先執行後端、前端及發布檔案檢查；通過才部署 `web/`。不會發布 `.runtime/`、`.env`、SQLite、APK 或錄影。
4. 在 Actions 確認 deployment 成功，再開啟正式網址。

相關操作依 [GitHub 官方 Pages 工作流程](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) 設定。

## 本機服務

在 Mac 專案目錄執行：

```sh
python3 scripts/configure_pages_service.py https://luke79210-hue.github.io/adb/
scripts/run-service.sh python3 mock
```

這會設定精確的 GitHub Pages origin；不會改為 LAN 公開監聽。設定會保存至 Git 忽略的 `.env`，並保留原本其他環境設定。

若要登入後常駐啟動（先停止手動啟動的服務）：

```sh
scripts/service.sh install mock
scripts/service.sh status
```

登入服務會安裝於 `~/Library/Application Support/Ultron ADB QA/app/`，資料與日誌保存在同層 `data/`。首次安裝會用 SQLite backup API 遷移專案內的資料庫（包含尚在 WAL 的交易）與媒體；後續重新安裝只更新程式與設定，保留資料。這避免 launchd 直接讀取 Documents 保護目錄。修改專案的 `.env` 或程式後，重新執行 `scripts/service.sh install mock` 更新安裝副本。

真實模式則需先安裝 Google 官方 Android platform-tools、設定 `ADB_PATH` 與真正的 `ULTRON_PACKAGE`，將 mock 改成 real。缺少設備、ADB 或公司 APP 套件設定時，不能將模擬展示視為真實設備已可操作。

## 網站配對

1. 在**同一台 Mac** 開啟 `http://127.0.0.1:8765/`。
2. 在「服務設定與診斷」點「複製權杖」。
3. 開啟正式 GitHub Pages 網站，在配對欄貼上權杖，按「配對並連線」。不要將權杖貼入 GitHub、Issues、Actions secrets 或聊天。
4. 若瀏覽器要求本機／區域網路存取權限，確認網站來源後允許。瀏覽器可能限制公開 HTTPS 網站連線到 loopback；不支援時請使用本機頁面，勿停用瀏覽器安全保護。

配對權杖每次服務重啟都會改變，只存於網站分頁的 sessionStorage。公開網站無法直接取得權杖；配對後仍需通過本機的 Host／Origin／token 驗證。`127.0.0.1` 指向開啟網站的電腦，不是 GitHub 的伺服器，也不是其他人的 Mac。

瀏覽器權限行為參考 [Chrome 官方 Local Network Access 說明](https://developer.chrome.com/blog/local-network-access)。

## 保留與回復

來源以 Git commit 保存。要回復前端時，在 GitHub 選取先前驗證的 commit 版本，完成變更後再明確觸發發布。SQLite 及媒體為 Mac 本機資料，不會隨 GitHub Pages 的前端回復而變更。
