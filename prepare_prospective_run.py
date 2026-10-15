"""Create dated pipeline plans; does not acquire data, schedule jobs or seal a signal."""
import argparse
import datetime as dt
import json
from pathlib import Path
from research_runtime import atomic_json, utcnow


def prepare(date):
    day=dt.date.fromisoformat(date)
    if day.isoformat()!=date:raise ValueError('ISO signal day required')
    run=f'inputs/prospective/{day:%Y%m%d}'
    target=Path(f'configs/prospective/{day:%Y%m%d}')
    if target.exists():raise FileExistsError('Plans already exist: '+str(target))
    # Preserve the reviewed stage dependencies in the original pipeline templates.
    plans={}
    for stage in ('source','replay','seal'):
        text=Path(f'configs/tpex_prospective_{stage}_pipeline.json').read_text()
        plans[stage]=json.loads(text.replace('inputs/prospective/20261015',run).replace('2026-10-15',date))
    target.mkdir(parents=True)
    for stage,plan in plans.items():atomic_json(target/f'{stage}.json',plan)
    atomic_json(target/'preparation.json',dict(signal_date=date,run_root=run,prepared_at=utcnow(),status='plans_only_awaiting_source_cutoff',source_not_before=f'{date}T15:00:00+08:00',scheduled_service=False))
    print(target)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--date',required=True);a=p.parse_args();prepare(a.date)
