"""Process-local wrapper for the separately frozen cash-merger source pilot.

Uses the existing bounded source checkpoint machinery. Importing this wrapper
does not configure another pilot, inspect saved bodies, or make network calls.
The draft policy has no valid freeze until the parent CB checkpoint is pinned.
"""
import argparse
from pathlib import Path

import frontier_sources


ROOT = Path('inputs/cash_merger_20261021')
OUT = Path('deliverables/cash_merger_20261021')
POLICY = Path('configs/cash_merger_protocol_20261021.json')


def _source_module():
    # Each pipeline stage is a distinct process. Do not use this module to run
    # simultaneous pilots within one interpreter: the shared implementation's
    # paths are deliberately configured for this one process only.
    frontier_sources.ROOT = ROOT
    frontier_sources.OUT = OUT
    frontier_sources.POLICY = POLICY
    return frontier_sources


def plan(batch='discovery'):
    return _source_module().plan(batch)


def acquire(batch='discovery'):
    return _source_module().acquire(batch)


def package(batch='discovery'):
    return _source_module().package(batch)


def verify(batch='discovery'):
    return _source_module().verify(batch)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['acquire', 'package', 'verify'])
    parser.add_argument('--batch', default='discovery')
    args = parser.parse_args()
    globals()[args.stage](args.batch)
