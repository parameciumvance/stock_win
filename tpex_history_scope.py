"""Explicit historical acquisition scope; classification confidence stays unchanged."""
import datetime,json
from pathlib import Path

def validate_source_year(year, month=1, scope_path=Path('configs/tpex_history_scope.json')):
    cutoff=datetime.date.fromisoformat(json.loads(Path('configs/tpex_pool_policy.json').read_text())['research_asof'])
    if not 1<=month<=12 or year>cutoff.year:
        raise ValueError('Outside research date scope')
    if year<2020:
        scope=json.loads(Path(scope_path).read_text())
        if year<scope['earliest_year'] or year>scope['requested_end_year']:
            raise ValueError('Outside approved historical source scope')
        evidence=scope.get('rule_evidence',[])
        if len(evidence)<2 or any(datetime.date.fromisoformat(e['published_on'])>=datetime.date(year,1,1) for e in evidence):
            raise ValueError('Historical coding evidence must precede source year')
    if datetime.date(year,month,1)>cutoff:
        raise ValueError('Beyond research cutoff')
    return cutoff
