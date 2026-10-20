"""Compare saved M35 date partitions without manufacturing a historical census.

This module performs no I/O.  Callers must verify and read back their source
archives before supplying the original response bytes.  A matching set of
current official responses is evidence of partition agreement, not proof of
historical first availability or of the absence of withdrawn announcements.
"""
import calendar
import json

from buyback_announcement_index import parse_index


MONTHS = tuple(f'2024-{month:02d}' for month in range(1, 13))
BOUNDARY_SCOPES = {
    '2023Q4': ('2023-10-01', '2023-12-31'),
    '2025Q1': ('2025-01-01', '2025-03-31'),
}


def _keys(bodies, expected, label):
    if not isinstance(bodies, dict) or set(bodies) != set(expected):
        raise ValueError(label + ' must contain exactly: ' + ', '.join(expected))


def _parse(body, start, end, label):
    try:
        return parse_index(body, start=start, end=end)
    except (TypeError, ValueError) as error:
        raise ValueError(label + ': ' + str(error)) from error


def _json_value(value):
    # JSON type identity matters: False and 0 compare equal in Python but are
    # different original source values.  Object display order is immaterial.
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _field_differences(annual, monthly):
    differences = []
    for field in sorted(annual.keys() | monthly.keys()):
        annual_present, monthly_present = field in annual, field in monthly
        if (annual_present and monthly_present
                and _json_value(annual[field]) == _json_value(monthly[field])):
            continue
        item = dict(field=field, annual_present=annual_present,
                    monthly_present=monthly_present)
        if annual_present:
            item['annual_value'] = annual[field]
        if monthly_present:
            item['monthly_value'] = monthly[field]
        differences.append(item)
    return differences


def reconcile(annual_body: bytes, monthly_bodies: dict[str, bytes],
              boundary_bodies: dict[str, bytes]) -> dict:
    """Validate fixed response scopes and retain all partition disagreements.

    The annual response remains the original frozen reference.  Every monthly
    response remains separate; no union replaces that reference or silently
    fills a missing row.  Boundary responses are validated on their own actual
    announcement dates and are never included in the 2024 comparison.  Missing
    ``total`` metadata does not prevent a comparison, while the underlying
    parser still rejects malformed records, duplicate identities and ceilings.

    Format and scope errors raise ``ValueError``.  Valid but changed responses
    return an explicit false agreement and full source rows for each change.
    Empty successful responses can agree without certifying an empty universe.
    """
    _keys(monthly_bodies, MONTHS, 'monthly_bodies')
    _keys(boundary_bodies, BOUNDARY_SCOPES, 'boundary_bodies')
    annual = _parse(annual_body, '2024-01-01', '2024-12-31', 'annual')
    monthly = {}
    for month in MONTHS:
        number = int(month[-2:])
        end = f'{month}-{calendar.monthrange(2024, number)[1]:02d}'
        monthly[month] = _parse(monthly_bodies[month], month + '-01', end,
                                'month ' + month)
    boundaries = {
        label: _parse(boundary_bodies[label], start, end, 'boundary ' + label)
        for label, (start, end) in BOUNDARY_SCOPES.items()
    }

    annual_rows = {row['event_id']: row for row in annual['rows']}
    partition_rows = {}
    for month, index in monthly.items():
        for row in index['rows']:
            identity = row['event_id']
            if identity in partition_rows:
                # Normally impossible after exact date-scope validation, but
                # do not let a future parser change silently collapse a row.
                raise ValueError('Duplicate identity across monthly partitions: ' + identity)
            partition_rows[identity] = (month, row)

    missing, new, changed = [], [], []
    for identity in sorted(annual_rows.keys() - partition_rows.keys()):
        missing.append(dict(event_id=identity, annual_row=annual_rows[identity]))
    for identity in sorted(partition_rows.keys() - annual_rows.keys()):
        month, row = partition_rows[identity]
        new.append(dict(event_id=identity, month=month, monthly_row=row))
    for identity in sorted(annual_rows.keys() & partition_rows.keys()):
        month, row = partition_rows[identity]
        original = annual_rows[identity]
        fields = _field_differences(original['original_fields'], row['original_fields'])
        if fields:
            changed.append(dict(event_id=identity, month=month,
                                field_differences=fields,
                                annual_row=original, monthly_row=row))

    agreement = not (missing or new or changed)
    return dict(
        status=('current_snapshot_partitions_agree' if agreement
                else 'current_snapshot_partitions_differ'),
        current_snapshot_partition_agreement=agreement,
        differences=dict(missing_from_monthly=missing, new_in_monthly=new,
                         changed_original_fields=changed),
        annual_index=annual,
        monthly_indices=monthly,
        monthly_counts={month: index['current_response_row_count']
                        for month, index in monthly.items()},
        monthly_total_returned_rows=len(partition_rows),
        boundary_indices=boundaries,
        boundary_rows_merged_into_2024=False,
        current_snapshot_only=True,
        complete_announcement_population_verified=False,
        empty_universe_verified=False,
        historical_pit_verified=False,
        first_publication_time_verified=False,
        source_gate_passed=False,
        profit_edge_proven=False,
    )
