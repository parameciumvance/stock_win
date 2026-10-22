"""Conditional cash/deadline arithmetic; unknown actual inputs never become claims.

Source interpretation and freshness must be independently verified before these
pure helpers can calculate. There is no quote reader, weekday calendar default,
tax-rate guess, order path, or inference that an old contract has expired.
"""
from bisect import bisect_right
import datetime as dt
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import re


REQUIRED_FACTS = (
    'current_version_at_entry', 'all_closing_conditions', 'final_conversion_date',
    'final_consideration_per_share', 'lawful_withholding_twd', 'eligible_registered_ordinary_shares',
    'holder_is_buyer_or_nominee', 'holder_exercises_dissenters_rights',
    'holder_has_unvested_employee_shares',
)
PAYMENT_BUSINESS_DAYS = 7


def require(condition, message):
    if not condition:
        raise ValueError(message)


def iso_day(value):
    require(isinstance(value, str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value),
            'Date must be a canonical ISO calendar day')
    return dt.date.fromisoformat(value)


def _evidence(value):
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, dict) and bool(item) or isinstance(item, str) and bool(item.strip()) for item in value)


def _decimal(value, label):
    require(isinstance(value, (str, Decimal)), label + ' must preserve a decimal string/Decimal, never float/bool')
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(label + ' must be a finite decimal') from error
    require(result.is_finite(), label + ' must be a finite decimal')
    return result


def net_cash(shares, consideration_per_share, withholding_twd):
    """Deduct verified withholding first, then round half up to whole TWD."""
    require(type(shares) is int and shares > 0, 'Eligible shares must be a positive integer, never bool/float')
    consideration = _decimal(consideration_per_share, 'Final consideration')
    withholding = _decimal(withholding_twd, 'Lawful withholding')
    require(consideration > 0 and withholding >= 0, 'Consideration must be positive and withholding nonnegative')
    precision = max(50, len(str(shares)) + len(consideration.as_tuple().digits)
                    + len(withholding.as_tuple().digits) + abs(consideration.as_tuple().exponent)
                    + abs(withholding.as_tuple().exponent) + 10)
    with localcontext() as context:
        context.prec = precision
        gross = Decimal(shares) * consideration
        require(withholding <= gross, 'Withholding exceeds this cash consideration')
        unrounded = gross - withholding
        cash = unrounded.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return dict(gross_twd=str(gross), withholding_twd=str(withholding),
                unrounded_net_twd=str(unrounded), cash=str(cash),
                rounding='Deduct lawful withholding, then ROUND_HALF_UP to one TWD')


def validate_calendar(calendar):
    require(isinstance(calendar, dict), 'Applicable business calendar must be explicit')
    require(calendar.get('verified') is True, 'Applicable calendar must be independently verified')
    require(isinstance(calendar.get('basis'), str) and calendar['basis'].strip() and _evidence(calendar.get('evidence')),
            'Applicable calendar needs its explicit contractual/legal basis and evidence')
    first, last = iso_day(calendar['start']), iso_day(calendar['end'])
    require(first <= last, 'Calendar coverage start follows end')
    days = calendar['business_days']
    require(isinstance(days, list), 'Explicit applicable business_days must be a list')
    parsed = [iso_day(day) for day in days]
    require(parsed == sorted(set(parsed)), 'Business calendar must be strictly sorted and duplicate-free')
    require(all(first <= day <= last for day in parsed), 'Business day lies outside declared calendar coverage')
    return first, last, parsed


def payment_deadline(final_conversion_date, calendar):
    """Seventh supplied applicable business day strictly after the final base."""
    base = iso_day(final_conversion_date)
    first, last, days = validate_calendar(calendar)
    require(first <= base <= last, 'Calendar does not cover the verified conversion base')
    position = bisect_right(days, base) + PAYMENT_BUSINESS_DAYS - 1
    require(position < len(days), 'Calendar has insufficient future business-day coverage')
    return days[position].isoformat()


def six_month_reference(contract_copy_date):
    """Original unextended calendar-month day only; never an expiry conclusion."""
    copy = iso_day(contract_copy_date)
    serial = copy.year * 12 + copy.month - 1 + 6
    try:
        return dt.date(serial // 12, serial % 12 + 1, copy.day).isoformat()
    except ValueError as error:
        raise ValueError('A month-end convention requires separately verified source interpretation') from error


def _verified_fact(facts, name, reasons):
    fact = facts.get(name)
    if fact is None:
        reasons.append(name + '_unknown')
        return None
    require(isinstance(fact, dict), 'Each actual fact must have value/verified/evidence fields')
    verified, value = fact.get('verified'), fact.get('value')
    require(verified is None or type(verified) is bool, 'Fact verified must be True/False/null, never integer')
    provisional = fact.get('provisional', False)
    require(type(provisional) is bool, 'Fact provisional must be boolean')
    if provisional:
        reasons.append(name + '_provisional')
    elif value is None:
        reasons.append(name + '_unknown')
    elif verified is not True:
        reasons.append(name + '_unverified')
    elif not _evidence(fact.get('evidence')):
        reasons.append(name + '_evidence_missing')
    else:
        return value
    return None


def evaluate_claim(case):
    """JSON-compatible all-or-nothing current-claim gate, with explicit gaps."""
    require(isinstance(case, dict) and isinstance(case.get('facts', {}), dict), 'Case facts must be a mapping')
    reasons, facts = [], case.get('facts', {})
    values = {name: _verified_fact(facts, name, reasons) for name in REQUIRED_FACTS}
    for name, required in [('current_version_at_entry', True), ('all_closing_conditions', True),
                           ('holder_is_buyer_or_nominee', False), ('holder_exercises_dissenters_rights', False),
                           ('holder_has_unvested_employee_shares', False)]:
        value = values[name]
        if value is not None:
            require(type(value) is bool, name + ' must be a boolean actual fact')
            if value is not required:
                reasons.append(name + ('_not_confirmed' if required else '_excluded'))
    if values['final_conversion_date'] is not None:
        iso_day(values['final_conversion_date'])
    # Invalid verified numerical inputs fail even if another fact remains unknown.
    price, tax, shares = (values[name] for name in ('final_consideration_per_share', 'lawful_withholding_twd',
                                                  'eligible_registered_ordinary_shares'))
    if price is not None:
        require(_decimal(price, 'Final consideration') > 0, 'Final consideration must be positive')
    if tax is not None:
        require(_decimal(tax, 'Lawful withholding') >= 0, 'Lawful withholding must be nonnegative')
    if shares is not None:
        require(type(shares) is int and shares > 0, 'Eligible shares must be a positive integer, never bool/float')
    calendar = case.get('business_calendar')
    if calendar is None:
        reasons.append('applicable_business_calendar_unknown')
    else:
        require(isinstance(calendar, dict), 'Business calendar must be a mapping or null')
        verified = calendar.get('verified')
        require(verified is None or type(verified) is bool, 'Calendar verified must be True/False/null')
        if verified is not True:
            reasons.append('applicable_business_calendar_unverified')
        else:
            validate_calendar(calendar)
    reference = six_month_reference(case['contract_copy_date']) if case.get('contract_copy_date') is not None else None
    extension, extension_deadline = case.get('written_extension'), None
    if extension is not None:
        require(isinstance(extension, dict), 'Written extension must be a mapping or null')
        require(extension.get('verified') is None or type(extension.get('verified')) is bool,
                'Extension verified must be True/False/null')
        if extension.get('verified') is True:
            require(_evidence(extension.get('evidence')), 'Verified written extension needs source evidence')
            extension_deadline = iso_day(extension['deadline']).isoformat()
    result = dict(status='actual_inputs_incomplete' if reasons else 'verified_inputs_arithmetic_pending',
        calculation_ready=False, reasons=reasons, payment_date=None, cash=None,
        payment_date_meaning='Contractual latest payment day, not evidence of bank receipt', cash_currency='TWD',
        payment_business_days_after_base=7, conversion_base_included=False,
        original_unextended_six_month_day=reference, verified_written_extension_deadline=extension_deadline,
        termination_conclusion=None, automatic_expiry_inferred=False,
        six_month_rule_meaning='Conditional termination if conditions unmet/unwaived by the applicable deadline; latest terms required',
        voting_bookclosure_used=False, provisional_terms_used=False,
        source_gate_passed=False, cash_claim_source_gate_passed=False,
        historical_pit_verified=False, profit_edge_proven=False,
        valid_prospective_signal_date=None, market_prices_or_returns_read=False, orders_authorized=False)
    if reasons:
        return result
    try:
        due = payment_deadline(values['final_conversion_date'], calendar)
    except ValueError as error:
        if str(error).startswith(('Calendar does not cover', 'Calendar has insufficient')):
            reasons.append('applicable_business_calendar_coverage_insufficient')
            result['status'] = 'actual_inputs_incomplete'
            return result
        raise
    money = net_cash(shares, price, tax)
    result.update(status='verified_conditional_cash_and_deadline_calculated', calculation_ready=True,
                  payment_date=due, cash=money['cash'], cash_calculation=money)
    return result
