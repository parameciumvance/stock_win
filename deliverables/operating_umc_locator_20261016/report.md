# 聯電SEC索引匯入與候選申報定位

使用者提供`CIK0001033767.json`，原樣匯入119,674 bytes，SHA `c63c1f0e8187cf01dcd59d0aabd1e676f073e117023e30cadd94016016d50a7c`；Windows來源與WSL保存雜湊一致，Zone.Identifier HostUrl符合官方submissions URL。先封存、Windows備份取回並核驗SHA／manifest／CRC，再讀取索引。未變更凍結研究協定，亦未替換既有原文。

CIK及公司名稱、recent陣列長度及accession唯一性驗收通過；共738列，定位2025-01-21的6-K候選1份。這是以已知2024Q4盈餘公告日期定位候選，不是靠索引即宣稱財務季度已驗證；reportDate及acceptanceDateTime原樣保留在candidates.json。尤其JSON的Z標記不直接升為已核實UTC，仍需原始SGML／索引交叉核對。

- [完整申報原文](https://www.sec.gov/Archives/edgar/data/1033767/000095017025006966/0000950170-25-006966.txt)；[申報索引](https://www.sec.gov/Archives/edgar/data/1033767/000095017025006966/0000950170-25-006966-index.htm)；主文件 `6k_on_01212025.htm`。

使用Desktop Commander與兩個worker，對候選的完整申報與索引做一次有界下載；實際HTTP結果：403、403。原始回應、headers、時間及雜湊再打包，Windows備份取回、manifest與CRC核對通過。checkpoint SHA `c43adec854375cfbbe12d13aa09b218caa8a008cd8b51d0fc3ee1368c6b4f88f`，同電腦不同檔案系統，不宣稱離機備份。HTTP403原文只作錯誤證據，不當成SEC文件。

是否取得可待核驗完整原文：False。索引本身不是盈餘附件／6-K原文，也不足以驗證接受時間、首次公開或修訂歷程。已取得數值的公司季仍是兩家公司2024Q4；台積電完整SEC匯入的先前結果維持，聯電仍未通過SEC原文／時間核對，未新增建模資料或計算預測誤差，七規則每日計畫仍停止。

若下載仍被拒，請只將上述候選完整申報`.txt`由一般瀏覽器存到Downloads後提供路徑；聯電PDF、這份JSON與已驗收台積電檔案不需重傳。拿到原文後須核對CIK、主文件與EX附件、實際財務季度及毛利率／EPS／營收，再核對接受時間。
