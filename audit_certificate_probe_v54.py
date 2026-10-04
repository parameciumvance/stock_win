"""Audit a narrow certificate-quote probe against archived 2025 quotes."""
import argparse
import json
from pathlib import Path

import pandas as pd


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--probe', type=Path, default=Path('upload/certificate_quote_probe.json'))
    p.add_argument('--quotes', type=Path, default=Path('inputs/quotes_twse_2025.csv.gz'))
    p.add_argument('--output', type=Path, default=Path('deliverables/certificate_probe_audit_v54.md'))
    a = p.parse_args()
    probe = json.loads(a.probe.read_text())
    expected = {(date, category) for date in ('20250812', '20251002')
                for category in ('ALLBUT0999', 'ALL')}
    if len(probe) != 4 or {(x['date'], x['category']) for x in probe} != expected:
        raise ValueError('Unexpected probe date/category coverage')
    q = pd.read_csv(a.quotes, dtype={'symbol': str})
    records = []
    for item in probe:
        if item.get('error') or item.get('matching_count') != len(item.get('matching_rows', [])):
            raise ValueError('Probe has an error or inconsistent row count')
        day = f"{item['date'][:4]}-{item['date'][4:6]}-{item['date'][6:]}"
        rows = {r['symbol']: r for r in item['matching_rows']}
        if set(rows) != {'2493', '2855'}:
            raise ValueError('Unexpected potential matches')
        for symbol in ('2493', '2855'):
            historical = q[(q.date.eq(day)) & (q.symbol.eq(symbol))]
            if len(historical) != 1:
                raise ValueError('Missing or duplicated archived parent quote')
            row = rows[symbol]
            if row['name'] != historical.iloc[0]['name'] or float(row['close'].replace(',', '')) != historical.iloc[0]['close']:
                raise ValueError('Probe and archived quote differ')
            records.append((day, item['category'], symbol, row['name'], row['close']))
    lines = '\n'.join(f'| {day} | {category} | {symbol} {name} | {close} |'
                      for day, category, symbol, name, close in records)
    report = f'''# 2855／2493 新股權利證書行情探查稽核

收到的 `certificate_quote_probe.json` 自述來源為四次官方端點回應；它是**篩選摘要**，不是完整原始 JSON。程式逐列檢查日期、分類、代號、名稱和收盤價，八筆母股列均與已封存的 `quotes_twse_2025.csv.gz` 一致。

## Tasks

- [x] 核對 2025-08-12 和 2025-10-02 的 `ALLBUT0999`／`ALL` 四組摘要均未記錄錯誤，且各有 2855、2493 兩個匹配列。
- [x] 核對兩種查詢的母股名稱和收盤價與封存行情一致。
- [ ] 待取得完整原始回應、公告中的憑證識別與集保交付規則後，再決定憑證是否共代號／共行情及如何記帳；實股 NAV 閘門維持。

| 日期 | 行情分類 | 摘要中匹配代號 | 收盤價 |
|---|---|---|---:|
{lines}

原探查程式只保留代號以 `2855`／`2493` 開頭或名稱包含「權利證書」的列。依這份摘要，`ALL` 相比 `ALLBUT0999` 在兩日沒有多出符合篩選條件的列；**不能**據此證明憑證與母股共享代號／價格，也不能排除以其他代號或名稱呈現、或行情合併於母股列的情形。摘要沒有原始回應的雜湊或完整欄位，無法獨立重驗篩選是否漏列。

下一步規劃：若重新啟動憑證項目，先保存這兩日完整 `MI_INDEX` 原始 JSON 與回應雜湊，對照上市公告的證券識別及集保入帳、換發日；再以整股／畸零規則重跑受阻持股帳。2023 年原始資料尚未提供，跨年度模型仍等待資料。

重算：`python3 audit_certificate_probe_v54.py --probe upload/certificate_quote_probe.json --quotes inputs/quotes_twse_2025.csv.gz`。
'''
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(report)


if __name__ == '__main__':
    main()
