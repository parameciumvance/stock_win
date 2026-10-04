"""Summarize v54 held-action diagnostics without treating conditional rows as valid NAV."""
import argparse
import csv
import gzip
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--replay', type=Path, default=Path('restored_v54/twse_history/output_research_v54'))
    cli.add_argument('--model', type=Path, default=Path('restored_v54/twse_history/output_research_v5'))
    cli.add_argument('--output', type=Path, default=Path('deliverables'))
    cli.add_argument('--quotes', type=Path, default=Path('inputs/quotes_twse_2025.csv.gz'))
    args = cli.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    summary = json.loads((args.replay / 'summary.json').read_text())
    model = json.loads((args.model / 'summary.json').read_text())

    with (args.replay / 'held_action_audit.csv').open(newline='') as f:
        held = list(csv.DictReader(f))
    with gzip.open(args.quotes, 'rt', encoding='utf-8-sig', newline='') as f:
        quote_rows = list(csv.DictReader(f))
    related_other_codes = {r['symbol'] for r in quote_rows
                           if r['symbol'].startswith(('2855', '2493'))
                           and r['symbol'] not in ('2855', '2493')}
    named_certificate_rows = sum('權利證書' in r['name'] for r in quote_rows)
    parent_dates = {(r['date'], r['symbol']) for r in quote_rows if r['symbol'] in ('2855', '2493')}
    for pair in (('2025-08-12', '2855'), ('2025-09-04', '2493'),
                 ('2025-10-02', '2493')):
        if pair not in parent_dates:
            raise ValueError('Missing ordinary-share quote: ' + repr(pair))
    unresolved = [r for r in held if r['status'].startswith('unresolved')]
    if not all(r['valid_before_unresolved'] == 'False' for r in unresolved):
        raise ValueError('An unresolved row unexpectedly marked valid')
    by_event = defaultdict(list)
    for row in unresolved:
        by_event[row['event_id']].append(row)
    gate_methods = defaultdict(list)
    for method, gate in summary['first_unresolved'].items():
        gate_methods[gate['event_id']].append(method)
    with (args.replay / 'daily_accounting_status.csv').open(newline='') as f:
        days = list(csv.DictReader(f))
    daily = defaultdict(list)
    for row in days:
        daily[row['method']].append(row)

    inventory = []
    for event_id, rows in by_event.items():
        example = rows[0]
        methods = sorted({row['method'] for row in rows})
        inventory.append(dict(date=example['date'], event_id=event_id,
                              symbol=example['symbol'], event_type=example['event_type'],
                              status=example['status'], held_rows=len(rows),
                              distinct_methods=len(methods), methods='|'.join(methods),
                              first_gate_for='|'.join(sorted(gate_methods.get(event_id, []))),
                              classification='confirmed_first_gate' if event_id in gate_methods
                              else 'conditional_candidate'))
    inventory.sort(key=lambda row: (row['date'], row['event_type'], row['event_id']))
    fields = list(inventory[0])
    with (args.output / 'unresolved_action_inventory_v54.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(inventory)

    gates = []
    for method in ('equal', 'momentum_60_skip5', 'logistic', 'hist_gradient_boosting'):
        records = daily[method]
        complete = sum(r['accounting_complete'] == 'True' for r in records)
        nav = sum(bool(r['nav_if_complete']) for r in records)
        gate = summary['first_unresolved'][method]
        assert records[complete]['date'] == gate['date']
        gates.append(dict(method=method, first_gate_date=gate['date'],
                          first_gate_event_id=gate['event_id'],
                          total_days=len(records), complete_days=complete,
                          nav_days=nav, days_after_first_gate=len(records)-complete,
                          complete_days_without_nav=complete-nav))
    with (args.output / 'strategy_gate_impact_v54.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(gates[0]))
        writer.writeheader()
        writer.writerows(gates)

    if len(unresolved) != 182 or len(inventory) != 149 or sum(g['complete_days'] for g in gates) != 618:
        raise ValueError('Unexpected v54 baseline; recheck source/version')
    model_metrics = model['metrics']
    counts = Counter(row['event_type'] for row in inventory)
    with gzip.open(args.model / 'holdout_predictions_2025.csv.gz', 'rt', newline='') as f:
        predictions = list(csv.DictReader(f))
    by_day = defaultdict(list)
    for row in predictions:
        by_day[row['date']].append(row)
    by_month = defaultdict(list)
    for date, rows in sorted(by_day.items()):
        top_n = math.ceil(.1 * len(rows))
        positives = sum(r['surge_adjusted'] == 'True' for r in rows)
        result = dict(date=date, day_prevalence=positives / len(rows))
        for method in ('logistic', 'hist_gradient_boosting'):
            top = sorted(rows, key=lambda row: float(row[method]), reverse=True)[:top_n]
            result[method] = sum(r['surge_adjusted'] == 'True' for r in top) / top_n
        by_month[date[:7]].append(result)
    monthly = []
    for month, records in sorted(by_month.items()):
        n = len(records)
        monthly.append(dict(month=month, evaluable_days=n,
                            prevalence_mean_by_day=sum(r['day_prevalence'] for r in records)/n,
                            logistic_top_decile_precision_mean=sum(r['logistic'] for r in records)/n,
                            hgb_top_decile_precision_mean=sum(r['hist_gradient_boosting'] for r in records)/n))
    for method, field in [('logistic', 'logistic'), ('hist_gradient_boosting', 'hist_gradient_boosting')]:
        mean = sum(r[method] for records in by_month.values() for r in records) / len(by_day)
        if abs(mean-model_metrics[field]['precision_top_decile_mean_by_day']) > 1e-12:
            raise ValueError('Daily Top 10% did not reproduce the archived v5 metric')
    with (args.output / 'monthly_signal_diagnostics_v54.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(monthly[0]))
        writer.writeheader()
        writer.writerows(monthly)
    monthly_lines = [f'| {m["month"]} | {m["evaluable_days"]} | '
                     f'{m["prevalence_mean_by_day"]:.1%} | '
                     f'{m["logistic_top_decile_precision_mean"]:.1%} | '
                     f'{m["hgb_top_decile_precision_mean"]:.1%} |' for m in monthly]
    model_lines = []
    for method, label in [('logistic', 'Logistic'),
                          ('hist_gradient_boosting', 'HistGradientBoosting')]:
        m = model_metrics[method]
        model_lines.append(f'| {label} | {m["pr_auc"]:.4f} | '
                           f'{m["precision_top_decile_mean_by_day"]:.2%} | '
                           f'{m["lift_top_decile_vs_prevalence"]:.2f}× |')
    gate_lines = []
    for g in gates:
        gate_lines.append(f'| {g["method"]} | {g["first_gate_date"]}／'
                          f'{g["first_gate_event_id"]} | {g["complete_days"]} | '
                          f'{g["nav_days"]} | {g["days_after_first_gate"]} | '
                          f'{g["complete_days_without_nav"]} |')
    duplicate_rows = len(unresolved) - len(inventory)
    report = f'''# 台股研究 v54：待查事件去重與模型訊號評估

基準：2025 年 243 個交易日、四個股票策略；僅採已封存的 v54 資料。研究帳採小數股與條件式 OHLC 成交假設。

## Tasks 檢核表

- [x] 從 v54 正式封存恢復逐日帳與持股事件，不沿用未封存的 v55–v58 輸出。
- [x] 列出 {len(unresolved)} 筆未解持股紀錄，去重為 {len(inventory)} 個候選事件；跨策略重複列 {duplicate_rows} 筆。
- [x] 區分 {len(gate_methods)} 個不同的已確認首個阻塞事件與 {len(inventory)-len(gate_methods)} 個後段條件式候選事件。
- [x] 單獨呈現 2025 留出集模型排序評估，不把代理組合回報稱為可交易績效。
- [x] 用逐日預測重算 {len(by_day)} 個可評估日的每月 Top 10% precision，與封存的全年平均完全吻合。
- [x] 另將兩模型與既定 60 日去近 5 日動能、20 日動能在相同 2025 留出列比較；詳 `signal_rule_comparison_v54.md`。
- [x] 查核現有免費行情檔中的 2855／2493：指定交易日只有四位母股代號列，另有母股前綴代號 {len(related_other_codes)} 種、名稱含「權利證書」 {named_certificate_rows} 列；尚不能判定憑證是否與母股共用行情。
- [ ] Pending：核實各新股權利證書與母股是否共代號、共行情，以及整股／畸零與發款捨入；保留估值閘門。
- [x] 用既有 2024 特徵與標籤完成 10／11 月兩個隔離訓練標籤的早期時間切分壓力測試；詳 `early_temporal_stress_v54.md`。
- [x] 分解 2025 歷史普通股池的缺標籤與訊號篩選範圍；詳 `label_coverage_audit_v54.md`。
- [x] 以 2024／2025 共同的 7–11 月區間核對合格覆蓋率和正例率的跨年變動；詳 `label_coverage_audit_v54.md`。
- [ ] 多年度 walk-forward、不同市場環境和完整同口徑實股回測。

## 待查事件到底有多少

| 口徑 | 數量 | 解讀 |
|---|---:|---|
| 回放中的未解持股列 | {len(unresolved)} | 同事件在不同策略持有可重複。 |
| 不同候選事件 | {len(inventory)} | 事件類型：{', '.join(f'{k} {v}' for k,v in sorted(counts.items()))}。 |
| 已確認的不同首個阻塞 | {len(gate_methods)} | 等權 2886、動能 3535、兩模型共用 2493。 |
| 後段條件式候選 | {len(inventory)-len(gate_methods)} | 原帳已在首個阻塞後失效；重新處理第一筆可能改變後續持股與事件集合，不能視為固定待辦。 |

原始 2025 持股與官方事件交集有 632 個不同事件（包含已解與未解）；目前的 {len(inventory)} 個候選只是 v54 的條件式診斷口徑，並非「632 減已完成數」的精確餘額。證書行情、停牌標價與整股結算也不是單純股利公告的數量問題。

「首個阻塞」是**現行保守回放程式的閘門**，並非已證實三檔證券都缺獨立行情。若查明憑證與普通股共用代號／價格，須修正持股權益與估值規則，再整段回放；屆時候選事件和可標價日數都要重新計算。

## 首個阻塞對日數的影響

| 策略 | 首個阻塞 | 完整帳日 | 可標價 NAV 日 | 首阻塞後日數 | 完整帳但缺價日 |
|---|---|---:|---:|---:|---:|
{chr(10).join(gate_lines)}

合計 {sum(g['complete_days'] for g in gates)}/{sum(g['total_days'] for g in gates)} 個策略日帳務完整；另有 {sum(g['complete_days_without_nav'] for g in gates)} 個完整帳日因缺行情而不能標價，只有 {sum(g['nav_days'] for g in gates)} 個策略日具 NAV。首阻塞後日數相加為 {sum(g['days_after_first_gate'] for g in gates)}，**不是可以歸因到各事件的獨立損失天數**：清掉一筆後，下一筆阻塞會接手。`strategy_gate_impact_v54.csv` 列出每個策略的界線。

## 模型訊號評估（2025 留出集）

2024 訓練 {model['training_rows']:,} 筆、正例 {model['training_positives']:,}；2025 留出 {model['evaluation_rows']:,} 筆、正例 {model['evaluation_positives']:,}（{model_metrics['prevalence']:.2%}）。目標是未來 20 個市場交易日內盤中最高價較訊號收盤價上漲至少 30%；使用事前可得量價特徵。

| 模型 | PR-AUC | 每日 Top 10% precision | 相對正例率 lift |
|---|---:|---:|---:|
{chr(10).join(model_lines)}

隨機排序的 PR-AUC 參考約 {model_metrics['random_pr_auc_baseline']:.4f}。留出集結果顯示排序訊號，**不代表 15% 的選股交易勝率或實際獲利**。v5 的還原價代理報酬尚缺完整股利、交付、證書和真實成交檢驗，不應與 0050 的實股總報酬直接比較。現在只有一個 2024→2025 切分，尚無多折 walk-forward。

| 月份 | 可評估日 | 當日正例率平均 | Logistic 前 10% | 梯度樹前 10% |
|---|---:|---:|---:|---:|
{chr(10).join(monthly_lines)}

每月差異很大，且 12 月只有 2 個可評估日（未來 20 日標籤要在封存資料內結束）；日與日的標籤窗口重疊，不能把月表當作獨立的 12 次測試。`monthly_signal_diagnostics_v54.csv` 保留未四捨五入值。

同列簡單規則對照：既定 `mom60_skip5` 逐日 Top 10% 正例率 11.94%，20 日動能 13.00%；Logistic 15.13%，梯度樹 12.89%。模型的 PR-AUC 與完整月表、20 日相位敏感性詳 `signal_rule_comparison_v54.md`。該比較尚未證明扣成本後有超額報酬。

後續 2024 早期時間切分壓力測試的合併 42 日：Logistic 7.17%、梯度樹 7.85%、既定 60 日規則 7.48%；Logistic 未勝過規則。2024 訓練期短，這是看過 2025 結果後設計的回溯檢查，細節及邊界見 `early_temporal_stress_v54.md`。

2025 歷史普通股池 254,096 股票日中，28,628 缺未來 20 日標籤；另有 85,981 雖有標籤但不符合訊號資格。模型可評估的 139,487 股票日只佔原始股票池 54.90%，其 5.29% 正例率不適用於被排除的股票。各月與缺值理由見 `label_coverage_audit_v54.md`。

相同 7–11 月口徑下，2024 有 71,329／105,204（67.80%）股票日符合模型評估，合格正例率 3.77%；2025 有 64,176／110,316（58.17%），合格正例率 6.91%。年初 120 日特徵暖機及 2025 年末標籤截尾會扭曲全年佔比，故以共同月份展示；這個描述性差異仍不能解釋成模型績效。

## 免費資料來源核查與日期修正

2493 揚博 2025-09-04 是現金每股 4 元加每千股配 108 股的**除權息交易日**；2025-10-02 才開始新股權利證書交易，不能將 09-04 記作「證書缺價」的起日。2855 統一證的新股權利證書則自 2025-08-12 交易，至 09-10 換成增資普通股。證交所設有新股權利證書買賣辦法，但具體代號及行情共享方式須依當年實際公告查證。

**編碼勘誤：**先前以 2009 年舊版條文「四位股票代號＋L–Z」推斷憑證行情缺漏，這個推斷不成立。2024-12-31 修訂、適用 2025 年的證券市場編碼原則已沒有該條。2025 年證交所公告甚至把 2887 普通股新股權利證書標為「股票代碼 2887」，故不能預設所有新股權利證書都有另一個代號或獨立收盤價。本專案 `inputs/quotes_twse_2025.csv.gz` 全年共 {len(quote_rows):,} 列，2855／2493 的指定日期有母股代號，另以這兩檔為前綴的代號 {len(related_other_codes)} 種、名稱含「權利證書」 {named_certificate_rows} 列。此項掃描**不能判斷**憑證是否與母股共用同一行情。現有 `fetch_quotes.py` 使用 `MI_INDEX?type=ALLBUT0999`，正規化並未按四位普通股代號過濾；需核實交易所公告的實際代號、行情如何合併，以及集保入帳。此問題尚未解決，故仍不應自行假設價格或發布全年實股績效。

查詢入口：[證交所每日收盤行情](https://www.twse.com.tw/zh/trading/historical/mi-index.html)；[2025 適用編碼原則](https://twse-regulation.twse.com.tw/TW/law/DAT0201.aspx?FLCODE=FL033103)；[2887 公告與新股權利證書代碼](https://www.tsholdings.com.tw/tsh/issue/issue3/1752563173071/)；[證書買賣辦法](https://twse-regulation.twse.com.tw/TW/law/DAT0201.aspx?FLCODE=FL007359)；[2493 當時除權公告轉載](https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=94caef53-cfe9-497a-99bc-c7bee84ae2e5)；[2493 證書上市公告轉載](https://anuenews.cnyes.com/news/id/6165295)。

## 下一步規劃

1. 先擴充免費歷史行情年份和當時普通股池，再以隔離標籤窗口的跨年度 walk-forward 檢查 precision／lift 穩定性。延伸年度須逐年重建特徵、標籤與缺值統計。
2. Pending：等權 08-07 六筆（2886 等）、動能 08-15 3535、09-04 的 2493 除權息；以及 2855／2493 證書代號行情和整股畸零結算。日後重新啟動時可用 `probe_twse_certificate_quotes.py --dates 20250812 20251002` 核對官方 JSON。
3. 只有完整實股帳及估值後才計算全年 Alpha。

生成：`python3 audit_backlog_v54.py --replay restored_v54/twse_history/output_research_v54 --model restored_v54/twse_history/output_research_v5 --quotes inputs/quotes_twse_2025.csv.gz --output deliverables`。
'''
    (args.output / 'backlog_and_model_status_v54.md').write_text(report)
    print(json.dumps(dict(unresolved_rows=len(unresolved), unique_candidates=len(inventory),
                          first_gate_events=len(gate_methods), strategy_days=sum(g['total_days'] for g in gates),
                          complete_days=sum(g['complete_days'] for g in gates),
                          nav_days=sum(g['nav_days'] for g in gates),
                          outputs=[str(p) for p in args.output.iterdir()]), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
