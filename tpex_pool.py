"""Accepted exploratory ordinary-stock policy; confidence travels with every quote."""
import re
from tpex_classification_pilot import parse_isin
from tpex_type_recovery import parse_single

def classify(code, known, exact):
    if code in exact:
        e=exact[code]
        if e['issue_type']=='普通股' and e['cfi'].startswith('ES'):
            return 'confirmed_ordinary',e['cfi']
        return 'confirmed_nonordinary',e['cfi']
    if code in known:
        e=known[code]
        if e['group']=='股票' and e['cfi'].startswith('ES'):
            return 'confirmed_ordinary',e['cfi']
        if e['group']=='股票':return 'unresolved_conflicting_evidence',e['cfi']
        return 'confirmed_nonordinary',e['cfi']
    if re.fullmatch(r'[0-9]{4}',code):return 'ordinary_stock_rule_candidate',''
    return 'unresolved_nonordinary_type',''

def source_types(root):
    p=root/'classification'
    known=parse_isin((p/'isin.raw').read_bytes())
    for k,v in parse_isin((p/'isin_listed.raw').read_bytes()).items():
        if k in known and known[k]['cfi']!=v['cfi']:raise ValueError('ISIN source conflict '+k)
        known.setdefault(k,v)
    exact=parse_single((p/'unknown_single_query.html').read_bytes())
    return known,exact
