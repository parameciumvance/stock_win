"""Paired daily differences with block-resampling sensitivity, research only."""
from pathlib import Path

import pandas as pd

from audit_temporal_uncertainty_v54 import bootstrap_gap


OUT=Path(__file__).resolve().parent/"deliverables"


def main():
    vol=pd.read_csv(OUT/"volatility_baseline_daily_v79.csv")
    barrier=pd.read_csv(OUT/"entry_barrier_daily_v80.csv")
    rows=[]
    for year in (2024,2025,2026):
        for source,data,cols in (
            ("surge",vol,["top10_hit"]),
            ("entry",barrier,["target_rate","barrier_net50bp",
                               "fixed20_relative50bp"])):
            group=data[data.year.eq(year)].sort_values("date")
            assert group.date.is_unique and len(group)>150
            for baseline in ("volatility20","atr14"):
                for metric in cols:
                    score=group[f"logistic_{metric}"]-group[f"{baseline}_{metric}"]
                    for block in (20,40):
                        q,p=bootstrap_gap(score.to_numpy(),block=block,
                                          repetitions=5000,
                                          seed=20261005+year+block+len(metric))
                        rows.append(dict(year=year,dataset=source,metric=metric,
                                         comparison=f"logistic-{baseline}",days=len(group),
                                         block_days=block,observed_gap=float(score.mean()),
                                         q025=float(q[0]),q975=float(q[2]),
                                         fraction_nonpositive=p))
    out=pd.DataFrame(rows)
    out.to_csv(OUT/"volatility_paired_blocks_v81.csv",index=False)
    print(out[out.block_days.eq(20)].to_string(index=False))


if __name__=="__main__":
    main()
