# 營運預測試點與有限失敗歸因

2026-10-16使用者採納方向建議。本輪先做一次可恢復凍結輸入的失敗歸因，再以兩家晶圓代工公司做營運公告資料試點；七規則252日每日計畫仍停止。

## 已完成的有限歸因

[報告](../deliverables/reassessment_20261016/report.md)使用原上市法人研究2024～2026截至10/02的20日逐日結果與精確匹配價格檔，拆開選股、股票池及成本。原始ZIP整包SHA／506個manifest成員／CRC、備份取回均通過；沒有用新快照替換。

三年度共同池未扣成本即落後0050約2.07～2.91個百分點；假設成本再拖累約1.58～1.65個百分點。模型相對同池的增量跨年不穩定。這是原先要求未來報價完整的條件池、重疊窗口均值，不是年度NAV或因果識別。TPEx共同矩陣與逐股明細未在本地，因此沒有宣稱已完成上櫃七法逐股歸因。

## 固定營運試點

協定：[configs/research_reassessment_20261016.json](../configs/research_reassessment_20261016.json)。2330台積電及2303聯電，各2023Q1～2025Q4連續12季；選擇理由是會計／業務口徑及官方申報路徑，不依股票報酬選公司。它不是代表全市場的股票池。

第一目標是下一季合併毛利率，先與上一季、去年同季及可比管理層財測比較。資料完整時最多僅16組共同預測目標，這個規模只驗證來源與簡單基準，不訓練高維價格模型。若原始版本／時間不齊，就停在來源關卡，不以現在靜態表替代。此次沒有訓練新模型或計算預測勝率。

## 目前外部依賴

8個具體官方路徑請求回HTTP403，含SEC submissions、6-K原文、兩家公司IR頁、台積電PDF與新聞稿；明示User-Agent的SEC重試亦403，未留精確時刻者不補造。聯電2024Q4季報的官網直接PDF及備援CDN均成功下載，兩者bytes及SHA完全一致：

- 官方來源頁：https://www.umc.com/en/Download/quarterly_results/QuarterlyResultsDetail/2024/2024Q4
- 官方PDF：https://www.umc.com/upload/media/08_Investors/Financials/Quarterly_Results/Quarterly_2020-2029_English_pdf/2024/Q4_2024/UMC24Q4_report.pdf
- 已保存的備援PDF：https://event-prod.zucast.com/attach/9ab58db49e24edb587d9623a01dd303d/51016/UMC24Q4_report.pdf
- PDF SHA：`64b73d8838d932aeb3c4d3f145953fdbc0236cf9341e46998ddd37b478ececec`

保存→備份→取回核驗後，已從第1頁重播毛利率30.4%、EPS0.68元、營收603.9億元及可見日期2025-01-21。原始PDF是13頁公開AES格式文件，使用固定pypdf／cryptography依賴讀取，沒有修改原文。

SEC接受時間、台灣首次公告時刻及完整修訂歷程仍未驗收；24個公司季無一列可升為正式建模資料。錯誤、原文、取得時間及缺口均已保存，不推定所有來源永久不可取得，也不猜測HTTP403根因。

若繼續，先將2330與2303的2024Q4原始盈餘公告／季報與對應SEC 6-K及接受時間索引放入 `inputs/operating_pilot_20261016/incoming/`，或提供可取得相同原文與時間證據的來源路徑。聯電PDF已取得，優先缺台積電原文與兩家的時間／版本證據；先兩組驗證路徑即可。SEC時間不能冒充台灣首次公開時間。不需券商或交易帳號憑證。

## 重播

```bash
uv pip install --python .venv/bin/python -r requirements_operating_pilot.txt
.venv/bin/python research_pipeline.py --plan configs/research_reassessment_pipeline.json --state-dir inputs/reassessment_20261016/pipeline
.venv/bin/python research_pipeline.py --plan configs/operating_source_pilot_pipeline.json --state-dir inputs/operating_pilot_20261016/pipeline
```

兩份plan驗收現有觀察及凍結輸入，不自動重試被拒來源或啟動每日服務。相關19項測試、程式與套件版本見`deliverables/reassessment_20261016/tests.json`。本地備份同檔案系統，大檔不提交Git。完整試點報告見[來源試點](../deliverables/operating_pilot_20261016/report.md)。
