"""Exact, explicitly hypothetical account paths for the already frozen IPO cohort."""
import argparse
import csv
from decimal import Decimal, localcontext
from fractions import Fraction
import gzip
from html.parser import HTMLParser
import io
import json
from math import lcm, prod
from pathlib import Path
import zipfile

from research_runtime import atomic_bytes, atomic_json, exclusive_lock, sha256
from source_checkpoint import package_sources, readback
from tender_preflight import verified_records

ROOT = Path('inputs/ipo_account_20261020')
OUT = Path('deliverables/ipo_account_20261020')
POLICY = Path('configs/ipo_account_protocol_20261020.json')
SOURCES = Path('configs/ipo_account_sources.json')


def policy():
    p = json.loads(POLICY.read_text())
    if sha256(POLICY) != json.loads((OUT/'protocol_freeze.json').read_text())['protocol_sha256']:
        raise ValueError('Frozen account protocol drift')
    for path, digest in p['inputs'].items():
        if sha256(Path(path)) != digest:
            raise ValueError('Pinned input drift: '+path)
    # Old checkpoint outputs must still exist with their original hashes.
    for name in ['ipo_screen_20261019', 'benchmark_cash_20261019']:
        c = json.loads(Path('deliverables', name, 'checkpoint.json').read_text())
        for path, digest in c['files'].items():
            if sha256(Path(path)) != digest:
                raise ValueError('Prior checkpoint drift: '+path)
    return p


def package():
    p = policy()
    cfg = json.loads(SOURCES.read_text()); raw = ROOT/'raw'
    if len(cfg['requests']) > p['source_request_bound']:
        raise ValueError('Frozen source request bound exceeded')
    results = json.loads((raw/'results.json').read_text())
    if results['config_sha256'] != sha256(SOURCES):
        raise ValueError('Source request configuration drift')
    verified_records(cfg, results, lambda name: (raw/name).read_bytes())
    entries = {'protocol.json': POLICY, 'requests.json': SOURCES}
    entries.update({'raw/'+path.name: path for path in raw.iterdir() if path.is_file()})
    with exclusive_lock(ROOT/'acquisition.lock'):
        package_sources(ROOT, OUT, 'sources', entries)


class Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def compact_html(body):
    parser = Text(); parser.feed(body.decode('utf-8'))
    return ''.join(''.join(parser.parts).split())


def sources():
    policy(); pkg, transfer = readback(OUT, 'sources')
    with zipfile.ZipFile(pkg['retrieved']) as z:
        data = {name: z.read(name) for name in z.namelist()}
    for key, path in [('protocol.json', POLICY), ('requests.json', SOURCES)]:
        import hashlib
        if hashlib.sha256(data[key]).hexdigest() != sha256(path):
            raise ValueError('Archive policy/request differs')
    results = json.loads(data['raw/results.json'])
    if results['config_sha256'] != sha256(SOURCES):
        raise ValueError('Archived request drift')
    records = verified_records(json.loads(SOURCES.read_text()), results, lambda n: data['raw/'+n])
    checks = []
    for filename, version in [('law_20231130.html', '112年11月30日'), ('law_20240627.html', '113年06月27日')]:
        r = next(r for r in records if r['request']['filename'] == filename)
        ok = False
        if r.get('http_status') == 200 and r.get('exit_code') == 0:
            text = compact_html(data['raw/'+filename])
            ok = all(v in text for v in [version, '每件處理費新台幣二十元', '未中籤人之申購處理費不予退回'])
        checks.append(dict(filename=filename, historical_text_and_20_fee_corroborated=ok,
                           scope='Selected historical version only; not proof of every intervening effective version or actual charges'))
    pdf = data.get('raw/6906.pdf', b''); pdfcheck = dict(symbol='6906', verified=False)
    pdf_record = next(r for r in records if r['request']['filename'] == '6906.pdf')
    if pdf_record.get('http_status') == 200 and pdf_record.get('exit_code') == 0 and pdf.startswith(b'%PDF-'):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf))
        text = ''.join(''.join(page.extract_text() or '' for page in reader.pages).split())
        required = ['6906', '118元', '申購處理費二十元', '工本費五十元', '113年1月5日', '113年1月8日', '113年1月10日']
        pdfcheck.update(verified=all(s in text for s in required), pages=len(reader.pages),
                        text_characters=len(text), missing_phrases=[s for s in required if s not in text],
                        scope='6906 alone:20/50fee,Jan5deposit,Jan8debit,Jan10refund instructions; no actual bank timestamps or all16coverage')
        atomic_bytes(ROOT/'6906_extracted.txt', (text+'\n').encode())
    atomic_json(OUT/'source_receipt.json', dict(archive_sha256=pkg['sha256'], manifest_files=pkg['manifest_files'],
                sha_crc_manifest_verified=True, backup=transfer, law_checks=checks, announcement=pdfcheck,
                observations=[dict(filename=r['request']['filename'], http_status=r.get('http_status'), exit_code=r.get('exit_code'),
                                   body_bytes=r.get('size_bytes'), stderr=r.get('stderr') if r.get('exit_code') != 0 else '') for r in records],
                all16_historical_fee_versions_verified=False, historical_pit_verified=False))


def number(value):
    result = Fraction(str(value).replace(',', ''))
    if result < 0:
        raise ValueError('Negative financial input')
    return result


def money(value):
    with localcontext() as c:
        c.prec = 42
        return str(Decimal(value.numerator)/Decimal(value.denominator))


def next_market(calendar, day, lag):
    if lag < 1 or day not in calendar or len(set(calendar)) != len(calendar) or calendar != sorted(calendar):
        raise ValueError('Missing/unordered calendar or invalid lag')
    i = calendar.index(day)+lag
    if i >= len(calendar):
        raise ValueError('Insufficient future market calendar')
    return calendar[i]


def integer_weights(probabilities):
    if not probabilities or any(not 0 <= p <= 1 for p in probabilities):
        raise ValueError('Invalid allocation probabilities')
    weights = [1]
    for p in probabilities:
        weights = [w*(p.denominator-p.numerator) for w in weights] + [w*p.numerator for w in weights]
    denominator = prod(p.denominator for p in probabilities)
    if sum(weights) != denominator:
        raise ValueError('Probability mass does not sum to one')
    return weights, denominator


def cash_events(rows, calendar, drag, application_fee, winner_fee):
    events = []
    for i, r in enumerate(rows):
        t = r['terms']; principal = number(t['offer_price'])*number(t['lot_size'])
        if not r['application_end'] < r['draw_date'] <= r['listing_date'] or r['application_end'] not in calendar:
            raise ValueError('Missing or inconsistent application dates')
        # Phase0: reserve before phase1 credits. This is not an extra debit next day.
        events += [(r['application_end'], 0, i, 'reserve', -(principal+application_fee+winner_fee)),
                   (next_market(calendar, r['draw_date'], 1), 1, i, 'refund_if_loss', principal+winner_fee),
                   (next_market(calendar, r['listing_date'], 2), 1, i, 'sale_if_win', number(r['raw_listing_quote']['open'])*number(t['lot_size'])*(1-drag))]
    return sorted(events)


def path_cash(events, mask, units):
    cash = 0; minimum = 0; ledger = []
    for day, phase, i, kind, amount in events:
        win = bool(mask & (1 << i))
        delta = int(amount*units) if kind == 'reserve' or (kind == 'refund_if_loss' and not win) or (kind == 'sale_if_win' and win) else 0
        cash += delta; minimum = min(minimum, cash)
        ledger.append((day, phase, i, kind, delta, cash))
    return cash, -minimum, ledger


def quantile(ordered, denominator, q):
    cumulative = 0
    for amount, weight in ordered:
        cumulative += weight
        if cumulative and cumulative*q.denominator >= denominator*q.numerator:
            return amount
    raise ValueError('Missing weighted quantile')


def calculate():
    p = policy()
    receipt = json.loads((OUT/'source_receipt.json').read_text())
    if not receipt['sha_crc_manifest_verified']:
        raise ValueError('Raw backup readback must precede account research')
    rows = sorted([r for r in json.loads(Path('deliverables/ipo_screen_20261019/matched_cases.json').read_text()) if r['eligible_for_calculation']], key=lambda r: (r['application_end'], r['symbol']))
    if len(rows) != 16 or len({r['symbol'] for r in rows}) != 16:
        raise ValueError('Frozen16case cohort changed')
    with gzip.open('inputs/benchmark_cash_20261019/market.csv.gz', 'rt') as source:
        calendar = [r['date'] for r in csv.DictReader(source)]
    a, w = number(p['application_fee_twd']), number(p['winner_fee_twd'])
    probabilities = []
    for r in rows:
        f = r['reported_fields']; lots = number(f['實際承銷股數'])/number(f['申購股數']); n = number(f['總合格件'])
        if lots.denominator != 1 or n.denominator != 1 or n <= 0:
            raise ValueError('Nonintegral allocation or zero qualified count')
        probabilities.append(min(Fraction(1), lots/n))
    weights, denominator = integer_weights(probabilities); scenarios = []; bulk = []
    for drag_text in p['sale_drag_scenarios']:
        drag = number(drag_text)
        if not 0 <= drag < 1:
            raise ValueError('Invalid cost scenario')
        events = cash_events(rows, calendar, drag, a, w)
        units = lcm(*(e[-1].denominator for e in events))
        increments = [number(r['terms']['lot_size'])*(number(r['raw_listing_quote']['open'])*(1-drag)-number(r['terms']['offer_price']))-w for r in rows]
        outcomes = {}; failures = 0; failed_weight = 0; peak = -1; peak_mask = None; weighted_sum = 0; paths = []
        for mask, weight in enumerate(weights):
            terminal, required, _ = path_cash(events, mask, units)
            expected_terminal = -a*len(rows)+sum((v for i, v in enumerate(increments) if mask & (1 << i)), Fraction(0))
            if terminal != expected_terminal*units:
                raise ValueError('Cash ledger / payoff conservation failed')
            if required > number(p['budget_twd'])*units:
                failures += 1; failed_weight += weight
            if required > peak:
                peak = required; peak_mask = mask
            outcomes[terminal] = outcomes.get(terminal, 0)+weight
            weighted_sum += terminal*weight
            paths.append([mask, str(weight), str(terminal), str(required)])
        factorized = -a*len(rows)+sum((prob*v for prob, v in zip(probabilities, increments)), Fraction(0))
        if Fraction(weighted_sum, denominator*units) != factorized:
            raise ValueError('Enumerated and marginal expectations differ')
        ordered = sorted((amount, weight) for amount, weight in outcomes.items() if weight)
        _, _, witness = path_cash(events, peak_mask, units)
        mass = lambda test: money(Fraction(sum(weight for amount, weight in ordered if test(amount)), denominator))
        scenarios.append(dict(sale_drag=drag_text, states=len(weights), independent_lottery_assumption=True,
            expected_twd=money(factorized), loss_probability=mass(lambda x: x < 0), zero_probability=mass(lambda x: x == 0), profit_probability=mass(lambda x: x > 0),
            quantiles_twd={str(q): money(Fraction(quantile(ordered, denominator, Fraction(q)), units)) for q in ['0.05', '0.5', '0.95']},
            worst_twd=money(Fraction(ordered[0][0], units)), best_twd=money(Fraction(ordered[-1][0], units)),
            no_win_probability=money(Fraction(weights[0], denominator)), no_win_loss_twd=money(-a*len(rows)),
            maximum_required_initial_cash_twd=money(Fraction(peak, units)), unfundable_states=failures, unfundable_probability=money(Fraction(failed_weight, denominator)),
            funding_scenario_all_states_pass=failures == 0,
            worst_funding_witness=dict(mask=peak_mask, wins=[r['symbol'] for i, r in enumerate(rows) if peak_mask & (1 << i)],
                ledger=[dict(date=e[0], phase=e[1], symbol=rows[e[2]]['symbol'], kind=e[3], delta_twd=money(Fraction(e[4], units)), cumulative_cashflow_twd=money(Fraction(e[5], units))) for e in witness])))
        bulk.append(dict(sale_drag=drag_text, units=str(units), denominator=str(denominator), paths=paths))
    atomic_bytes(ROOT/'paths.json.gz', gzip.compress(json.dumps(bulk, separators=(',', ':')).encode(), mtime=0))
    atomic_json(OUT/'calendar_and_terms.json', dict(calendar_sha256=p['inputs']['inputs/benchmark_cash_20261019/market.csv.gz'], calendar_start=calendar[0], calendar_end=calendar[-1], calendar_days=len(calendar),
        cases=[dict(symbol=r['symbol'], reserve_date=r['application_end'], draw_date=r['draw_date'], refund_date=next_market(calendar,r['draw_date'],1), listing_date=r['listing_date'], sale_cash_date=next_market(calendar,r['listing_date'],2), probability_exact=str(prob), principal_twd=money(number(r['terms']['offer_price'])*number(r['terms']['lot_size']))) for r, prob in zip(rows, probabilities)]))
    atomic_json(OUT/'summary.json', dict(status='completed_conditional_independent_account_and_cash_scenario_only', scenarios=scenarios,
        paths_sha256=sha256(ROOT/'paths.json.gz'), masks_per_scenario=len(weights), exact_mass_and_cash_conservation_verified=True,
        historical_pit_verified=False, actual_fills_verified=False, actual_bank_timestamps_verified=False, independence_verified=False,
        original_positive_marginal_screen_preserved=True, deployable_profit_edge_proven=False, valid_prospective_signal_date=None,
        decision='Retain small tool; finish this fixed cohort study without daily manual validation, parameter search or automatic expansion'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('stage', choices=['package', 'sources', 'calculate'])
    globals()[parser.parse_args().stage]()
