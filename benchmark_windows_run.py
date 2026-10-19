"""Bounded full-cohort adapter certification and read-only holding-window CLI."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

from benchmark_windows import load_verified, WindowUnavailable, direct_account
from research_runtime import atomic_json, sha256, utcnow

POLICY = Path('configs/benchmark_window_protocol_20261019.json')
OUT = Path('deliverables/benchmark_windows_20261019')


def policy():
    if sha256(POLICY) != json.loads((OUT / 'protocol_freeze.json').read_text())['protocol_sha256']:
        raise ValueError('Window protocol drift')
    return json.loads(POLICY.read_text())


def benchmark(c):
    return load_verified(c['source_checkpoint'], c['source_checkpoint_sha256'])


def verify():
    c = policy()
    b = benchmark(c)
    if str(b.clock[0].date()) != c['coverage_start'] or str(b.clock[-1].date()) != c['coverage_end']:
        raise ValueError('Verified source coverage differs')
    atomic_json(OUT / 'inputs_receipt.json', dict(status='passed', verified_at=utcnow(),
                checkpoint_sha256=c['source_checkpoint_sha256'], market_sessions=len(b.clock),
                source_provenance=b._provenance, new_downloads=0, archive_retransmissions=0))


def enumerate_windows():
    c = policy()
    b = benchmark(c)
    rows = []
    for horizon in c['horizon_market_sessions']:
        for index, date in enumerate(b.clock):
            entry = str(date.date())
            row = dict(entry=entry, horizon=horizon, exit=None, account=None)
            if index + horizon > len(b.clock):
                row['status'] = 'insufficient_horizon'
            else:
                row['exit'] = b.dates(entry, horizon)
                try:
                    row['account'] = b.window(entry, row['exit'])
                    row['status'] = 'accepted'
                except WindowUnavailable as error:
                    if 'Unquoted endpoint' not in str(error):
                        raise
                    row['status'] = 'unquoted_endpoint'
            rows.append(row)
    payload = (json.dumps(rows, allow_nan=False, sort_keys=True) + '\n').encode()
    (OUT / 'windows.json.gz').write_bytes(gzip.compress(payload, mtime=0))
    atomic_json(OUT / 'coverage.json', dict(status='full_cohort_enumerated', protocol_sha256=sha256(POLICY),
                attempts=len(rows), by_horizon={str(h): dict(Counter(r['status'] for r in rows if r['horizon'] == h)) for h in c['horizon_market_sessions']},
                windows_sha256=sha256(OUT / 'windows.json.gz'),
                purpose='Correctness and rejection coverage, no model, selection or return ranking'))


def audit_cases(rows, frame, distributions, split, horizons):
    """Independent grid plus closed-form endpoint accounts, preserving every rejection."""
    frame = frame.copy()
    frame['date'] = pd.to_datetime(frame.date)
    indexed = frame.set_index('date')
    clock = list(indexed.index)
    expected_keys = {(str(d.date()), h) for d in clock for h in horizons}
    actual_keys = [(r['entry'], r['horizon']) for r in rows]
    if len(actual_keys) != len(set(actual_keys)) or set(actual_keys) != expected_keys:
        raise ValueError('Window cohort missing/duplicated/extra')
    maximum, checked = 0., 0
    for row in rows:
        index = clock.index(pd.Timestamp(row['entry']))
        last = index + row['horizon'] - 1
        if last >= len(clock):
            status, exit_ = 'insufficient_horizon', None
        else:
            exit_ = str(clock[last].date())
            status = 'accepted' if np.isfinite(indexed.loc[clock[index], 'open']) and np.isfinite(indexed.loc[clock[last], 'close']) else 'unquoted_endpoint'
        if row['status'] != status or row['exit'] != exit_:
            raise ValueError('Independent window boundary/status differs')
        if status != 'accepted':
            if row['account'] is not None:
                raise ValueError('Rejected window was assigned a return')
            continue
        account = row['account']
        if account['entry'] != row['entry'] or account['exit'] != exit_ or account['market_sessions'] != row['horizon']:
            raise ValueError('Account endpoint identity differs')
        if account['symbol'] != '0050' or account['initial_units'] != 1000 or account['hypothetical_quote_acquisition'] is not True or account['source_verified'] is not True or any(account[k] for k in ['actual_fill_verified', 'historical_pit_verified', 'profit_edge_proven']):
            raise ValueError('Unverified accounting promotion')
        expected = direct_account(frame, distributions, split, row['entry'], exit_)
        for key, value in expected.items():
            if key == 'entitlements':
                if account[key] != value:
                    raise ValueError('Independent window entitlement differs')
            else:
                error = abs(account[key] - value)
                if not np.isfinite(error) or error > 1e-8:
                    raise ValueError('Independent terminal account differs: ' + key)
                maximum = max(maximum, error)
        if account['raw_entry_open'] != float(indexed.loc[clock[index], 'open']) or account['raw_exit_close'] != float(indexed.loc[clock[last], 'close']):
            raise ValueError('Endpoint quote provenance differs')
        if account['stale_market_sessions'] != int(indexed.iloc[index:last+1].close.isna().sum()):
            raise ValueError('Market clock was compressed')
        checked += 1
    return dict(status='passed', attempts=len(rows), accepted_accounts_verified=checked, max_absolute_terminal_error=maximum,
                rejected_windows_retained=len(rows)-checked, method='Independent full-grid enumeration and Decimal closed-form rights/cash/units')


def audit():
    c = policy()
    b = benchmark(c)
    coverage = json.loads((OUT / 'coverage.json').read_text())
    if coverage['windows_sha256'] != sha256(OUT / 'windows.json.gz') or coverage['protocol_sha256'] != sha256(POLICY):
        raise ValueError('Window artifacts drifted')
    rows = json.loads(gzip.decompress((OUT / 'windows.json.gz').read_bytes()))
    result = audit_cases(rows, b._frame, b._distributions, b._split, c['horizon_market_sessions'])
    counts = {str(h): dict(Counter(r['status'] for r in rows if r['horizon'] == h)) for h in c['horizon_market_sessions']}
    if coverage['attempts'] != len(rows) or coverage['by_horizon'] != counts:
        raise ValueError('Coverage summary differs')
    if any(r['account']['provenance'] != b._provenance for r in rows if r['status'] == 'accepted'):
        raise ValueError('Pinned window provenance differs')
    result.update(coverage_sha256=sha256(OUT / 'coverage.json'), windows_sha256=coverage['windows_sha256'])
    atomic_json(OUT / 'independent_audit.json', result)


def report():
    c = policy()
    coverage = json.loads((OUT / 'coverage.json').read_text())
    a = json.loads((OUT / 'independent_audit.json').read_text())
    if a['status'] != 'passed' or a['coverage_sha256'] != sha256(OUT / 'coverage.json'):
        raise ValueError('Independent complete-cohort audit required')
    lines = ['# 指定日期的0050毛額持有窗口', '',
             '上一輪基準代表2023年初取得、一路持有的股數與現金。後來新買入者不會接收舊持有人的配息權利或累積現金，因此不能把既有長期淨值比值直接當成任意進出日的新持有報酬。這不是修正上一輪的長期帳，而是新增用途不同、權利歸屬明確的介面。', '',
             '本輪零下載、零原始包重傳，沿用已封存取回的官方配息、分割與凍結原始報價。新協定固定2023-01-03～2025-12-31，20／60市場日，包含進入日；每個市場進入日全部保留，沒有依報酬選窗口、比較或重跑已停止策略。', '',
             '| 持有市場日 | 全部嘗試 | 可核對 | 端點無報價 | 完整期間不足 |', '|---|---:|---:|---:|---:|']
    for h in c['horizon_market_sessions']:
        counts = coverage['by_horizon'][str(h)]
        lines.append(f'| {h} | {sum(counts.values())} | {counts.get("accepted",0)} | {counts.get("unquoted_endpoint",0)} | {counts.get("insufficient_horizon",0)} |')
    lines += ['', f'獨立Decimal與完整群體核對{a["accepted_accounts_verified"]}個有效帳，保留{a["rejected_windows_retained"]}個拒絕窗口；最大終端欄位絕對誤差{a["max_absolute_terminal_error"]:.3g}。拒絕時不補零、不順延、不刪掉嘗試。', '',
              '全量覆蓋驗收只針對20與60市場日。介面也接受範圍內其他指定起迄／長度，沿用相同權益與端點檢查，但未全量驗收所有長度組合。', '',
              '## 使用方式與權利', '',
              '每次在指定日原始開盤報價假設取得1,000單位；沒有初始舊現金或舊應收。只認列「進入日之後、截止日當天以前或當天」除息的權利；截止時已發放為現金，未發放為應收。進入當天就是除息日，不取得該次權利；進入當天就是分割日，買到的已是分割後單位，不再乘4。', '',
              '```bash', '.venv/bin/python benchmark_windows_run.py query --entry 2025-01-17 --horizon 20', '.venv/bin/python benchmark_windows_run.py query --entry 2025-06-18 --exit 2025-07-21', '```', '',
              '只支援已核對的0050與資料範圍；停牌／非市場日／範圍外端點、無效日期、未知股票與被改動的來源檔均拒絕。停牌在窗口內仍計入市場日曆，僅可沿用已知停牌期間末次報價估值，不把無報價端點當可取得價格。程式不自動抓新資料或接受另一版本替代。', '',
              '公開查詢入口會驗證固定舊checkpoint SHA、全部依賴檔及官方來源封存取回。直接以自備DataFrame建立物件只供核對／測試，source_verified=False；不可冒充已核實來源。來源已核實也不代表歷史首次公開、券商實際入帳或成交已核實。', '',
              '## 邊界', '',
              '這是配息留現金的毛額原始收盤估值，不是投資人淨額、實際退出成交或可用買賣訊號；不含費用、稅務、滑價、利息與配息再投入。尚未支援其他股票公司行動，也不支援2026或資料範圍外窗口。它可作未來另立固定協定的衡量元件，不會自動替換舊研究的benchmark或恢復七規則每日計畫。', '',
              '見[完整窗口覆蓋](coverage.json)、[獨立重算](independent_audit.json)、[測試](tests.json)、[原始現金帳報告](../benchmark_cash_20261019/report.md)。舊協定、結果與檢查點均保留。']
    (OUT / 'report.md').write_text('\n'.join(lines)+'\n')
    atomic_json(OUT / 'next_tasks.json', dict(status='completed_verified_window_adapter', new_downloads=0,
                old_study_reruns=False, live_signals=False, profit_edge_proven=False, manual_daily_validation=False,
                seven_rule_daily_plan='stopped', next_use='Only a separately frozen future study may opt in; source/PIT/stock-accounting and execution limits remain'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['verify', 'enumerate_windows', 'audit', 'report', 'query'])
    parser.add_argument('--entry')
    parser.add_argument('--exit')
    parser.add_argument('--horizon', type=int, help='Positive market-session count; exhaustive certification covers 20 and 60 only')
    parser.add_argument('--symbol', default='0050')
    args = parser.parse_args()
    if args.stage == 'query':
        if not args.entry or (args.exit is None) == (args.horizon is None):
            parser.error('query requires --entry and exactly one of --exit / --horizon')
        try:
            b = benchmark(policy())
            exit_ = args.exit if args.exit is not None else b.dates(args.entry, args.horizon)
            print(json.dumps(b.window(args.entry, exit_, args.symbol), indent=2, allow_nan=False))
        except WindowUnavailable as error:
            parser.error(str(error))
    else:
        globals()[args.stage]()
