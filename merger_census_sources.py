"""Process-local source wrapper for the separately frozen 15-document census.

This continues the same cash-merger candidate after its 12-request discovery
pilot.  It does not alter that pilot's protocol, request ceiling or archives.
"""
import argparse
from pathlib import Path

import frontier_sources

ROOT = Path('inputs/cash_merger_census_20261021')
OUT = Path('deliverables/cash_merger_census_20261021')
POLICY = Path('configs/cash_merger_census_protocol_20261021.json')


def _source_module():
    frontier_sources.ROOT, frontier_sources.OUT, frontier_sources.POLICY = ROOT, OUT, POLICY
    return frontier_sources


def plan(batch='originals'):
    module = _source_module()
    result = module.plan(batch)
    from cash_merger_census import preflight
    preflight(module, batch, result[1])
    return result


def acquire(batch='originals'):
    plan(batch)
    return _source_module().acquire(batch)


def package(batch='originals'):
    plan(batch)
    return _source_module().package(batch)


def verify(batch='originals'):
    plan(batch)
    return _source_module().verify(batch)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['acquire', 'package', 'verify'])
    parser.add_argument('--batch', default='originals')
    args = parser.parse_args()
    globals()[args.stage](args.batch)
