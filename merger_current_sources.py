"""Bounded source wrapper for one current 6674 cash-conversion qualification.

Importing this module makes no requests. Source stages run in separate processes
and retain the native two-worker acquisition lock and checkpoint machinery.
"""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs

import frontier_sources


ROOT = Path('inputs/cash_merger_current_20261021')
OUT = Path('deliverables/cash_merger_current_20261021')
POLICY = Path('configs/cash_merger_current_protocol_20261021.json')
INDEX_CONFIG = Path('configs/cash_merger_current_index_sources_20261021.json')
INDEX_URL = 'https://mopsov.twse.com.tw/mops/web/ezsearch_query'


def validate_index_plan():
    """Validate issuer mode and all query fields without acquiring any bytes."""
    policy = json.loads(POLICY.read_text())
    config_body = INDEX_CONFIG.read_bytes()
    cfg = json.loads(config_body)
    reference = policy.get('batches', {}).get('index')
    if (not isinstance(reference, dict)
            or reference.get('path') != str(INDEX_CONFIG)
            or reference.get('requests') != 2
            or reference.get('sha256') != hashlib.sha256(config_body).hexdigest()):
        raise ValueError('Current index policy does not bind the validated configuration')
    queries = policy.get('index_queries')
    expected_queries = [
        dict(filename='target_6674_m00.json', issuer='6674', category='M00',
             start='2026-09-18', end='2026-10-21'),
        dict(filename='buyer_2324_m00.json', issuer='2324', category='M00',
             start='2026-09-18', end='2026-10-21'),
    ]
    if queries != expected_queries:
        raise ValueError('Current issuer/date/category query mapping drift')
    if (cfg.get('output_directory') != str(ROOT / 'raw_index')
            or cfg.get('allowed_hosts') != ['mopsov.twse.com.tw']
            or len(cfg.get('requests', [])) != 2):
        raise ValueError('Unexpected current index source configuration')
    for spec, request in zip(queries, cfg['requests']):
        if (set(request) != {'filename', 'url', 'method', 'data'}
                or request['filename'] != spec['filename']
                or request['url'] != INDEX_URL or request['method'] != 'POST'):
            raise ValueError('Current index route or file mapping drift')
        query = parse_qs(request['data'], keep_blank_values=True,
                         strict_parsing=True)
        expected = {
            'step': ['00'], 'RADIO_CM': ['2'], 'TYPEK': [''],
            'CO_MARKET': [''], 'CO_ID': [spec['issuer']],
            'PRO_ITEM': ['M00'], 'SUBJECT': [''],
            'SDATE': ['115/09/18'], 'EDATE': ['115/10/21'],
            'lang': ['TW'], 'AN': [''],
        }
        if query != expected:
            raise ValueError('Current index POST fields drift or duplicate keys')
    return cfg


def _source_module():
    validate_index_plan()
    # The generic source module is configured only for this stage's process.
    # Do not run simultaneous wrappers within the same Python interpreter.
    frontier_sources.ROOT = ROOT
    frontier_sources.OUT = OUT
    frontier_sources.POLICY = POLICY
    return frontier_sources


def plan(batch='index'):
    return _source_module().plan(batch)


def acquire(batch='index'):
    return _source_module().acquire(batch)


def package(batch='index'):
    return _source_module().package(batch)


def verify(batch='index'):
    return _source_module().verify(batch)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['acquire', 'package', 'verify'])
    parser.add_argument('--batch', default='index')
    args = parser.parse_args()
    globals()[args.stage](args.batch)
