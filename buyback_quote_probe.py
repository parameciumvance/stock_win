"""Pure calendar, Decimal return and fixed resource-screen calculations.

No prices, files or network sources are read here.  Callers must separately
verify the full market calendar, quote coverage and their frozen protocol.
These calculations do not establish historical point-in-time availability,
independent samples, actual execution or a profitable trading strategy.
"""
from collections import defaultdict
import datetime as dt
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
import re
from zoneinfo import ZoneInfo


_TAIPEI = ZoneInfo('Asia/Taipei')
_QUARTERS = tuple(f'2024Q{quarter}' for quarter in range(1, 5))


def _publication(value):
    if not isinstance(value, str):
        raise ValueError('Publication timestamp must be an ISO string with timezone')
    try:
        moment = dt.datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError('Invalid publication timestamp') from error
    if moment.utcoffset() is None:
        raise ValueError('Publication timestamp must have a timezone convertible to Taipei')
    return moment.astimezone(_TAIPEI)


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        raise ValueError('Market calendar must use ISO day strings')
    try:
        return dt.date.fromisoformat(value)
    except ValueError as error:
        raise ValueError('Invalid market calendar day') from error


def _decimal(value, label):
    # Decimal(float) preserves a binary approximation rather than source text.
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise ValueError(label + ' must retain its Decimal, integer or string value')
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(label + ' must be a valid Decimal value') from error
    if not number.is_finite():
        raise ValueError(label + ' must be finite')
    return number


def _cost(value):
    number = _decimal(value, 'cost')
    if not Decimal(0) <= number < Decimal(1):
        raise ValueError('cost must be in [0, 1)')
    return number


def _cost_key(value):
    if value == 0:
        return '0'
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def endpoints(calendar: list[str], publication_timestamp: str, horizon=20) -> tuple[str, str]:
    """Return next-market-day entry and the inclusive horizon's final session.

    Even a pre-open publication waits until a session strictly after its Taipei
    calendar date.  Missing quotes must not change these endpoints.  The input
    must be the caller's complete verified market calendar; a date list alone
    cannot detect an omitted real session in its interior.  A session on or
    before the publication date is required to establish the left boundary.
    """
    if not isinstance(calendar, list) or not calendar:
        raise ValueError('A nonempty verified market calendar is required')
    if type(horizon) is not int or horizon < 1:
        raise ValueError('horizon must be a positive integer')
    days = [_day(value) for value in calendar]
    if any(previous >= current for previous, current in zip(days, days[1:])):
        raise ValueError('Market calendar must be strictly sorted without duplicates')
    publication_day = _publication(publication_timestamp).date()
    if publication_day < days[0]:
        raise ValueError('Market calendar does not establish the publication left boundary')
    entry = next((i for i, day in enumerate(days) if day > publication_day), None)
    if entry is None or entry + horizon > len(days):
        raise ValueError('Market calendar lacks the fixed entry or complete holding horizon')
    return days[entry].isoformat(), days[entry + horizon - 1].isoformat()


def quote_change(entry, exit, cost) -> Decimal:
    """Compute (exit/entry)*(1-cost)/(1+cost)-1 from exact source numbers.

    These quote-based scenarios contain no assertion about fills, venue prices
    or minimum commissions.  A missing or invalid price fails rather than
    shifting the entry or exit to a different date.
    """
    initial, final, charge = _decimal(entry, 'entry'), _decimal(exit, 'exit'), _cost(cost)
    if initial <= 0 or final <= 0:
        raise ValueError('Entry and exit quotes must be strictly positive')
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        return (final / initial) * (Decimal(1) - charge) / (Decimal(1) + charge) - Decimal(1)


def _statistics(records):
    """Return exact-string summaries; issuer means do not imply independence."""
    result = dict(event_count=len(records), issuer_count=len({r['issuer'] for r in records}))
    by_issuer = defaultdict(list)
    for record in records:
        by_issuer[record['issuer']].append(record)
    for field in ('stock_change', 'benchmark_change', 'relative_change'):
        values = sorted(record[field] for record in records)
        size, middle = len(values), len(values) // 2
        result['mean_' + field] = str(sum(values, Decimal(0)) / size)
        result['median_' + field] = str(values[middle] if size % 2
                                        else (values[middle - 1] + values[middle]) / 2)
    result['issuer_means'] = {
        issuer: dict(event_count=len(group), **{
            'mean_' + field: str(sum((record[field] for record in group), Decimal(0)) / len(group))
            for field in ('stock_change', 'benchmark_change', 'relative_change')
        })
        for issuer, group in sorted(by_issuer.items())
    }
    return result


def aggregate(rows, primary_cost='0.005') -> dict:
    """Summarize a fixed 2024 event cohort without choosing favorable costs.

    Each row has case_id, issuer, publication_timestamp, cost, stock_change and
    benchmark_change.  Relative change is the arithmetic stock-minus-benchmark
    change.  Each case appears once per cost and retains the same issuer and
    publication across costs.  Coverage and matching populations are separate
    caller checks, not inferred from a favorable result here.

    The primary distribution rule uses only the specified cost: all four 2024
    publication quarters represented, at least three quarterly mean relative
    changes strictly positive, and pooled median relative change positive.
    Decimal summary values are strings suitable for hash-stable JSON output.
    """
    if not isinstance(rows, list):
        raise ValueError('rows must be a list of frozen event-cost records')
    primary = _cost_key(_cost(primary_cost))
    groups, identities, cases = defaultdict(list), set(), {}
    with localcontext() as context:
        context.prec = 50
        context.rounding = ROUND_HALF_EVEN
        for number, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                raise ValueError('Event-cost row must be a dictionary')
            try:
                case, issuer = row['case_id'], row['issuer']
                if not isinstance(case, str) or not case or not isinstance(issuer, str) or not issuer:
                    raise ValueError('case_id and issuer must be nonempty strings')
                publication = _publication(row['publication_timestamp'])
                if publication.year != 2024:
                    raise ValueError('Resource screen is fixed to 2024 publication events')
                cost = _cost_key(_cost(row['cost']))
                identity = case, cost
                if identity in identities:
                    raise ValueError('Duplicate case and cost: ' + case + ', ' + cost)
                source_identity = issuer, publication.isoformat()
                if case in cases and cases[case] != source_identity:
                    raise ValueError('A case changes issuer or publication across cost scenarios')
                stock = _decimal(row['stock_change'], 'stock_change')
                benchmark = _decimal(row['benchmark_change'], 'benchmark_change')
                record = dict(case_id=case, issuer=issuer,
                              publication_timestamp=publication.isoformat(),
                              quarter=f'{publication.year}Q{(publication.month - 1) // 3 + 1}',
                              stock_change=stock, benchmark_change=benchmark,
                              relative_change=stock - benchmark)
                identities.add(identity)
                cases[case] = source_identity
                groups[cost].append(record)
            except (KeyError, ValueError) as error:
                raise ValueError('Invalid event-cost row ' + str(number) + ': ' + str(error)) from error

        summaries = {}
        for cost, records in sorted(groups.items(), key=lambda item: Decimal(item[0])):
            summary = _statistics(records)
            summary['case_ids'] = sorted(record['case_id'] for record in records)
            summary['quarters'] = {
                quarter: _statistics([record for record in records if record['quarter'] == quarter])
                for quarter in _QUARTERS if any(record['quarter'] == quarter for record in records)
            }
            summaries[cost] = summary
        chosen = summaries.get(primary)
        missing_quarters = [quarter for quarter in _QUARTERS
                            if chosen is None or quarter not in chosen['quarters']]
        positive_quarters = ([] if chosen is None else [
            quarter for quarter, values in chosen['quarters'].items()
            if Decimal(values['mean_relative_change']) > 0
        ])
        positive_median = chosen is not None and Decimal(chosen['median_relative_change']) > 0
        passed = not missing_quarters and len(positive_quarters) >= 3 and positive_median

    return dict(
        status='fixed_quote_resource_screen_calculated', costs=summaries,
        primary_cost=primary, required_publication_quarters=list(_QUARTERS),
        primary_cost_present=chosen is not None,
        primary_missing_quarters=missing_quarters,
        primary_positive_mean_relative_quarters=positive_quarters,
        primary_pooled_median_relative_positive=positive_median,
        primary_distribution_rule_passed=passed,
        coverage_verified_by_caller=False, resource_allocation_gate_passed=False,
        relative_change_definition='stock_change_minus_benchmark_change',
        samples_independent=False, issuer_repetition_and_overlapping_horizons_possible=True,
        reused_historical_years=[2024], independent_holdout=False,
        multiple_research_attempts_reset=False,
        historical_pit_verified=False, profit_edge_proven=False,
        actual_execution_verified=False, valid_signal=False,
        valid_prospective_signal_date=None,
    )
