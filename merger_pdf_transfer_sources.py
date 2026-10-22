"""Retrieve only two exact generated artifacts, separately from UI discovery."""
import argparse
from pathlib import Path
import frontier_sources
ROOT=Path('inputs/cash_merger_pdf_transfer_20261022')
OUT=Path('deliverables/cash_merger_pdf_transfer_20261022')
POLICY=Path('configs/cash_merger_pdf_transfer_protocol_20261022.json')
def module():
    frontier_sources.ROOT,frontier_sources.OUT,frontier_sources.POLICY=ROOT,OUT,POLICY
    return frontier_sources
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['acquire','package','verify']);p.add_argument('--batch',default='files');a=p.parse_args();getattr(module(),a.stage)(a.batch)
