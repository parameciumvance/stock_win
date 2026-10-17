# 歷史公開時點與版本範圍續查

凍結研究協定SHA `b939e4271b1e3eca3757d8968a335b9f8902d0a870fbf33fd4b855d25942092b` 不變。既定關卡要求文件、版本、會計口徑與可驗證歷史時間；本輪未把嚴格「台灣第一次公開秒數／全世界所有修訂」當作已能查明的事實，也未另加可用資料的替代假設。來源時間仍有缺口，不自動升級建模。

## 實際新增

兩個worker的有界取得共6個請求：2個HTTP200、3個HTTP403、1個TimeoutError。原始成功／錯誤回應、headers、metadata、無回應逾時、web解析觀察筆記、凍結協定與先前來源包均先封存，再Windows備份取回，SHA／manifest／CRC通過後才解析PDF。checkpoint SHA `309a2d14b4be17d41755b3806c2825b84f186867f9c6eccfd3d2bff54e227d40`。同電腦跨檔案系統，未宣稱離機備份。

- 聯電[2024Q4法說邀請](https://www.umc.com/upload/media/08_Investors/Financials/Quarterly_Results/Quarterly_2020-2029_English_pdf/2024/Q4_2024/UMC24Q4_conference_call.pdf)，76,263 bytes：排定2025-01-21台北17:00／紐約04:00。這是排程，不是實際舉行、新聞稿公開或首次公告的證明，不能拿來替換SEC接受時間19:03:58。
- 台積電[同季WoG文件](https://investor.tsmc.com/schinese/encrypt/files/encrypt_file/qr/phase4_reports/2025-01/4403102dcea6b02abaf1bd9778ea69e0ec6b4ab0/4Q24EarningsRelease_WoG.pdf)，163,244 bytes：毛利率59%、EPS14.45、營收868.46十億元與凍結含財測PDF一致。本份是否含財測phrase：`False`。保留獨立SHA與來源，不替換舊PDF，不推斷兩者的先後／修訂順序。

## 版本盤點

重讀已封存的聯電submissions JSON（738列，1997-02-14～2026-10-13，files=[]）。在2025-01-21～2025-04-30的文件查核窗口，保留6-K、6-K/A、20-F、20-F/A全部候選；共11份，明示/A候選0份。這個窗口只界定待查文件，不當預測截止時間或已核實財務季度。

其中2025-03-20的`0001292814-25-000981`，reportDate=2024-12-31、主文件`umcfs4q24_6k.htm`，是普通6-K後續同結束日候選。原文請求本輪403，未將它直接定性成更正或拿它覆寫1/21版本。另有4/24的20-F同結束日候選，僅憑reportDate不能把年度文件當同一季度版本。沒有/A也不代表沒有普通6-K更新、刪除或SEC接受後更正；當前JSON快照不是完整版本證明。

## 時間證據限制與下一步

[SEC歷史PDS技術規格](https://www.sec.gov/info/edgar/specifications/pds-dissemination-spec030314.pdf)區分接受、重組文件與傳播，通常兩分鐘不是逐份文件的保證上界；規格也描述PAC可更改header、刪除申報，而不更新文件內文。此項由web工具解析，直接原始PDF請求403，已明示未取得raw，不把解析文字冒充原始來源。台積電[新聞頁](https://pr.tsmc.com/english/news/3201)解析只確認2025/01/16日期，原始HTML請求403；Business Wire逾時，不能升為可驗證的精確時間。

目前新增的是兩份同季佐證文件，沒有增加財務季度：仍兩家公司2024Q4有原文、22季缺原文，全部24列ready_for_model=False，模型／評估0。接受時間與聯電JSON五小時差異原樣保留；七規則每日計畫不恢復。

另找到[台積電公告轉載定位](https://news.cnyes.com/news/print/5839133)與[聯電公告轉載定位](https://news.cnyes.com/news/print/5843049)，分別列2025/01/16 15:40:39及2025/01/21 17:00:11。這是轉載的發言時間，非官方原件／首次公開證明；只作查找原公告的線索。MOPS官方舊入口由web工具導向error頁，API入口不可存取，未推測HTTP狀態。詳見[定位筆記](publication_locators.json)。

下一個具體外部依賴是這兩筆MOPS公告原件，以及[聯電3/20完整申報](https://www.sec.gov/Archives/edgar/data/1033767/000129281425000981/0001292814-25-000981.txt)的內容核對，以及兩組季度的文件公開時點／版本涵蓋證據。現有PDF、JSON與完整申報不需重傳。見[next_tasks.json](next_tasks.json)、[候選清單](umc_version_candidates.json)、[測試](tests.json)、[階段hash](pipeline_state.json)。
