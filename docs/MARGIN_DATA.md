# 免費融資融券資料與固定增量研究

官方來源為 TWSE MI_MARGN 的信用交易日報，與借券交易分開。取得 2023～2025 全年及 2026 截至 10/02；交易日曆與既有凍結價格區間一致。來源取得時間不冒充首次公告時刻，修訂軌跡未證實完整。

每份 JSON 保存 URL、HTTP 狀態、抓取時間與 hash。解析前檢查日期、16 欄 schema、唯一證券、非負数量及兩類餘額：融資＝前日＋買進−賣出−現金償還；融券＝前日＋賣出−買進−現券償還。ETF 代號可以含字母，普通股資格由凍結歷史股票池決定。官方 O／X／@／%／! 註記是次一營業日已公告狀況，不是當日真實成交紀錄。

## 事先固定的特徵與比較

所有特徵只使用前一市場日來源。融資與融券利用率＝當日餘額／（已公告次日限額＋1）；每日餘額變化＝（當日−前日）／（前日＋1），先逐日標準化再取完整 1／5／20 日平均；另有停止融資與停止融券兩個已公告狀態。比例固定截值，缺市場日不跨越、不補零，也不從缺列推斷信用交易資格。

`configs/margin_protocol.json` 固定 2024／2025／2026 的前一年年底 purged expanding 訓練、Ridge alpha=1000、Top10%、10／20／40 日配對 circular bootstrap。共同池包含量價、法人、45 日延遲營收與信用特徵；主比較三者＋信用相對三者，次比較量價＋信用相對量價，並列波動排序。選股前不檢查未來結果；選中端點未知時保留該股票、整組均值未知，不以已知結果替代。成本與 20 市場日持有不變。

## 接續與封存

```bash
make margin-fetch YEAR=2023
make margin-package YEAR=2023
make margin-fetch YEAR=2024
make margin-package YEAR=2024
make margin-fetch YEAR=2025
make margin-package YEAR=2025
make margin-fetch YEAR=2026 ASOF_ARGS="--asof 2026-10-02"
make margin-package YEAR=2026 ASOF_ARGS="--asof 2026-10-02"
make margin-diagnostics
make test-margin
```

來源完整的單一年度可先執行 `python3 audit_margin_increment.py --year 2024`，依相同固定設計產生年度結果；後續以 `--year 2025`／`--year 2026` 補入同一總表，無須重訓已完成年度。

每年先封存來源再續抓下一年。封存時從原始快取重新解析，逐列核對正規化 CSV，再檢查歷史普通股覆蓋、全部 member hash 與 ZIP CRC。既有快取不重新下載；首次錯誤取消尚未開始的年度請求，避免停止顯示進度後還等待整年排隊。

長時間執行環境可能失去程序連線，可使用 `python3 -m twse_history.margin --year 2025 --max-new-days 40 --fetch` 分批接續；每批先核對既有來源，只有全部市場日完整後才寫年度 CSV 與取得報告，部分快取不會冒充年度模型輸入。

價格、法人及日曆依 `docs/INSTITUTIONAL_RESUME.md` 恢復；營收依 `docs/REVENUE_PROXY.md` 復原。研究輸出在 `deliverables/margin/`，原始來源在 `inputs/margin/raw_年度/`。

本研究不代表獨立留出、年度 NAV 或實盤成交。若四類免費特徵仍不足以帶來穩定的成本後相對優勢，下一個需要決定的事項是是否改變持有期與換股頻率，應先重新固定設計，不能只挑較好的歷史結果。
