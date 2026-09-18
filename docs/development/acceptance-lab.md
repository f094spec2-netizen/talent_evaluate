# Agent 能力驗收台

## 瀏覽器操作

選 Agent → 選案例 → 試跑 → 查看輸入／預期／實際／證據 → 核准或退回答案 → 正式重跑。

答案核准確定標準，結果裁定處理語義評分；兩者分開留存。人工接受結果不能消除程式發現的關鍵錯誤。未核准的最新答案只能試跑，事後核准不追溯改寫舊試跑。修改答案必須建立新草稿版本，不能覆寫原答案或裁定。

左側可勾選多例；「整組」依資料分組執行。單例、開發分組或保留分組的成功都不等於完整首批驗收。下方可選不同批次比較；提供私有 JSON 匯出與當次程式快照 ZIP。

資料收集與總管**收件切片**呼叫真實處理器。其他七個 Agent 只有能力契約與案例規格，API 拒絕執行。完整總管 DAG、LLM 與人才定級未實作，不能以本台結果宣稱已完成。

## 案例與門檻

| 類別 | 數量 | 保存位置 |
|---|---:|---|
| 收集：新規範 | 12 | 公開合成生成器 |
| 收集：歷史格式 | 12 | 本地私有資料庫，不隨 Git 移動 |
| 收集：異常 | 12 | 公開合成生成器 |
| 總管收件 | 12 | 公開合成生成器 |

公開 CI 只有 36 個合成案例，不能冒稱完整業務驗收。本機首批為 48 個案例，標準答案由驗收者核准。格式覆蓋 HTML/HTM/JSON/CSV/XLSX/XLSM/DOCX；流程覆蓋正常收件、更新冪等、重傳、版本衝突、跨期重用、重試恢復與工作者崩潰。

每例固定來源家族及 development/holdout。導入器禁止同一 `source_family` 跨組；公開案例有独立合成來源命名空間，另檢查相同文件未跨組。私有來源依報告系列分組，不將相鄰週拆到兩組。

按 Agent、格式軌及版本分開計算：

- 自動正確率＝正確自動結果／全部自動結果，至少 95%。
- 自動覆蓋率＝自動完成的可判定案例／本組全部必要可判定案例，至少 80%；未選的必要案例仍在分母。
- 預期應交人工者不進覆蓋率分母，但必須正確升級；全為人工的軌顯示 N/A，不虛報 100%。
- 關鍵錯誤 0、必要案例全部完成、答案全部已核准、要求的證據皆可定位。
- 全部轉人工不能讓存在可判定案例的軌通過；任何失敗、缺例、人工退回或未完成的語義裁定均阻擋通過。
- 模型自評無放行權。未來 LLM 接口必須固定模型／提示版本，重跑同集三次且各次達標，不能平均；目前 API 不接受模型參數。

這是小型規則引擎基線，不是對未見材料的泛化證明。已使用過的保留集之後只是回歸集；引入模型前應補充未使用的來源家族。

## 私有材料

`python -m app.acceptance.private_cases PRIVATE_MANIFEST PRIVATE_CASES_JSON` 讀取本機來源路徑及**獨立擬定**的答案。保留 HTML 結構、期間標籤與日期候選；其餘文字一致代碼化，移除腳本、屬性、連結。原始路徑／文字對照只寫入同目錄 `deidentification-map.<hash>.private.json`，不導入網頁，修訂後不覆蓋舊對照。

這是結構脫敏，不是完成隱私審查的匿名化保證。日期候選也可能是業務數字，因此輸出始終標 `private_derived`，不得進公開 repo／CI。此批僅測收集與期間辨識，不可用於貢獻／潛力語義評估。部分案例明示補充已確認年份、類型、版本，以隔離歷史正文解析；不能假裝這些值來自原文。

導入命令：`python -m app.acceptance.cli import-private --file PRIVATE_CASES_JSON`。不自動核准。修改輸入須遞增 revision；改答案用網頁建立新版。舊案例與執行保留。

## 開發者啟動（驗收者不必操作終端）

Python 3.12，安裝既有 requirements 後：

```powershell
.venv/Scripts/python.exe -m app.acceptance.cli serve
```

綁定 `127.0.0.1:8765`，自動遷移、匯入公開案例及啟動單一內嵌佇列工作者。登入資訊自動產生於忽略的 `data/private/acceptance/local-access.json`，資料庫 `workbench.db` 與業務 `talent.db` 分離。不需 Telegram／模型 Token。不是 Windows 開機常駐服務；重啟電腦後由開發者重啟。

瀏覽器 QA 用 `serve --qa --port 8766`，資料放 `data/private/acceptance-qa/`，介面標 QA 操作演練；不得在真實案例庫代使用者核准。

基線：`python -m app.acceptance.cli baseline --split development --file data/private/acceptance/baseline.json`；分組可選 `holdout`、`all`。公開回歸：`python -m app.acceptance.cli public-regression --file output/public-acceptance-baseline.json`，須用不含私有資料的 CI 工作區。

## 持久化、權限與重現

- 獨立 FastAPI factory `app.acceptance.api:create_app`，與 Telegram API 分離。驗收資料庫含業務收件時拒絕啟動。
- 密碼至少 16 字元、scrypt 與常數時間比較；8 小時 HttpOnly、SameSite=Strict cookie，生產 Secure；密碼更換使舊 cookie 失效。CSRF、同源檢查、10 分鐘 10 次錯誤登入限制、1 MB 請求上限、CSP、所有來源均以文字顯示。
- 案例／答案／執行／結果／人工裁定／稽核／程式 ZIP 都持久化。首批小檔 bytes 以 base64 存在私有資料庫的不可變快照；不是公開靜態檔。S3 bucket 保留給後續大檔搬移，本期驗收附件尚未使用真實 S3。
- 每次固定 commit（若可用）、來源 hash、程式 ZIP、Python／主要依賴、資料集 hash、案例／答案／規則／評分器版本。ZIP 包含 app、migrations、requirements、Dockerfile，未提交開發基線也能保存當時原碼。加入 ZIP 功能前的最早基線僅有 hash，介面不提供不存在的快照。
- 另一電腦可使用 Git commit 或程式 ZIP 重建環境；私有 JSON 內包含完整輸入與標準答案。勿將匯出放公開儲存；重跑建立新執行，不能覆蓋歷史。
- 共同介面 `execute(agent, task)` 只收白名單輸入，答案、rubric、分組與評分不跨入處理器。
- 沿用 `agent_jobs`，驗收與業務工作者按 kind 分開領取。每例在新暫存資料庫／物件目錄呼叫真實下載、解析、總管；僅替換 Telegram 傳輸，另用受控時鐘加速重試。不是 live Telegram／S3 整合驗收。
- 每例交易寫入結果，工作者恢復時跳過已完成結果；租約耗盡明確失敗。單例須小於 lease（預設 300 秒）；接入長時間 LLM 前需另加心跳和超時。

受保護 API：`/api/overview`、`/api/cases`、`/api/cases/{id}/answers`、`/api/answers/{id}/decision`、`/api/runs`、`/api/runs/{id}`、`/api/results/{id}/adjudication`、`/api/audit`、`/api/code/{hash}`。登入用 `/api/login`；所有寫入均需 CSRF（登入另受同源檢查）。

## Railway 待接手

使用者尚未有帳號，已選先完成可操作版本，本次不建立雲端或付費資源。

帳號具備後建立獨立 evaluation 環境、PostgreSQL、私有 bucket。兩個 repo 服務分別選 `railway.acceptance-api.json` 和 `railway.acceptance-worker.json`，只 API 開 HTTPS 網域。兩服務設定 `APP_ENV=production`、`SERVICE_MODE=acceptance`、獨立 `DATABASE_URL`、隨機 `ACCEPTANCE_ADMIN_PASSWORD`、`ACCEPTANCE_EMBEDDED_WORKER=false`、S3 變數指向獨立 bucket。**不設定 Telegram 變數，不連正式資料庫。**

API pre-deploy 負責遷移與公開 seed；兩服務必須部署相同來源版本。開發者走私有通道導入脫敏案例，不導入原文／對照表。確認 HTTPS cookie、匿名拒絕、跨站拒絕、worker 失敗呈現及版本一致後再交付網址；真實 Telegram／S3 另驗。

配置依 [Railway 官方 Config as Code](https://docs.railway.com/config-as-code/reference)，尚未實際部署驗證。
