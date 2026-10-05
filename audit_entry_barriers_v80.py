"""Next-market-open entry and first-touch exit on daily regular-board OHLC.

This is a price-path label, not proof that any particular whole/odd-lot order
would have filled. No parameters are selected based on test-year outcomes.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from audit_volatility_baseline_v79 import METHODS, OUT, SOURCE, assemble

UP = .20
DOWN = .10
HORIZON = 20
FEE = .001425  # percentage-only illustrative charge; broker minimum not included
TAX = .003      # ordinary listed-stock sell-side illustrative tax
SLIPPAGE = .005 # each side, purely a fixed stress scenario


def _forward(a: np.ndarray, shift: int) -> np.ndarray:
    result=np.full(len(a),np.nan)
    if shift<len(a): result[:-shift]=a[shift:]
    return result


def first_touch(open_px: np.ndarray, high: np.ndarray, low: np.ndarray,
                close: np.ndarray, volume: np.ndarray) -> pd.DataFrame:
    """Status target/stop/timeout/censored per signal; same-day ambiguity -> stop.

    Signal is post-close day t; enter next market day's open t+1. Future gaps
    cross at that day's open; intraday crosses use barrier price. No intrabar
    time ordering is inferred. A missing quote censors only unresolved paths.
    """
    o,h,l,c,v=[np.asarray(x,dtype=float) for x in (open_px,high,low,close,volume)]
    n=len(o)
    assert all(len(x)==n for x in (h,l,c,v))
    entry=_forward(o,1)
    status=np.full(n,"censored",dtype="<U9")
    day=np.full(n,-1,dtype=int)
    exit_px=np.full(n,np.nan)
    both=np.zeros(n,dtype=bool)
    active=np.isfinite(entry) & (entry>0) & (np.arange(n)+HORIZON<n)
    target=entry*(1+UP); stop=entry*(1-DOWN)
    complete=np.ones(n,dtype=bool)
    for j in range(1,HORIZON+1):
        fo,fh,fl,fc,fv=(_forward(x,j) for x in (o,h,l,c,v))
        quote_ok=(np.isfinite(fo)&np.isfinite(fh)&np.isfinite(fl)&
                  np.isfinite(fc)&np.isfinite(fv)&(fo>0)&(fh>0)&
                  (fl>0)&(fc>0)&(fv>0))
        complete &= quote_ok
        active &= quote_ok
        if j>1:
            gap_stop=active & (fo<=stop)
            gap_target=active & (fo>=target)
            hit=gap_stop | gap_target
            status[gap_stop]="stop"
            status[gap_target]="target"
            day[hit]=j
            exit_px[hit]=fo[hit]
            active[hit]=False
        down=active & (fl<=stop)
        up=active & (fh>=target)
        both[down & up]=True
        status[down]="stop"
        status[up & ~down]="target"
        hit=down | up
        day[hit]=j
        exit_px[down]=stop[down]
        exit_px[up & ~down]=target[up & ~down]
        active[hit]=False
        if j==HORIZON:
            status[active]="timeout"
            day[active]=j
            exit_px[active]=fc[active]
            active[active]=False
    return pd.DataFrame({"entry_adj_open":entry,"outcome":status,
                         "exit_market_day":day,"exit_adj_price":exit_px,
                         "both_barriers_same_day":both,
                         "full20_quote_complete":complete,
                         "day20_adj_close":_forward(c,HORIZON)})


def net_return(entry: pd.Series, exit_px: pd.Series, slip: float) -> pd.Series:
    buy=entry*(1+slip)*(1+FEE)
    sale=exit_px*(1-slip)*(1-FEE)*(1-TAX)
    return sale/buy-1


def assemble_outcomes() -> pd.DataFrame:
    scored=assemble()
    prices=pd.read_csv(SOURCE / "prices_adjusted_2023_2026.csv.gz",
                       dtype={"symbol":str},parse_dates=["date"])
    calendar=pd.DatetimeIndex(sorted(prices.date.unique()))
    benchmark=prices[prices.symbol.eq("0050")].set_index("date").reindex(calendar)
    bench_entry=_forward(benchmark.adj_open.to_numpy(float),1)
    bench_exit=_forward(benchmark.adj_close.to_numpy(float),HORIZON)
    bench_relative=np.where(np.isfinite(bench_entry)&(bench_entry>0)&
                            np.isfinite(bench_exit)&(bench_exit>0),
                            bench_exit/bench_entry-1,np.nan)
    benchmark_frame=pd.DataFrame({"date":calendar,"benchmark_fixed20":bench_relative})
    frames=[]
    for symbol,g in prices[prices.symbol.ne("0050")].groupby("symbol",sort=True):
        g=g.set_index("date").reindex(calendar)
        outcome=first_touch(*(g[k].to_numpy(float) for k in
                              ("adj_open","adj_high","adj_low","adj_close","volume")))
        outcome.insert(0,"date",calendar)
        outcome.insert(1,"symbol",symbol)
        frames.append(outcome)
    labels=pd.concat(frames,ignore_index=True)
    out=scored.merge(labels,on=["date","symbol"],validate="one_to_one")
    out=out.merge(benchmark_frame,on="date",validate="many_to_one")
    assert len(out)==len(scored)
    out["barrier_net0_proxy"]=net_return(out.entry_adj_open,out.exit_adj_price,0)
    out["barrier_net50bp_proxy"]=net_return(out.entry_adj_open,out.exit_adj_price,SLIPPAGE)
    out["fixed20_net50bp_proxy"]=net_return(out.entry_adj_open,out.day20_adj_close,SLIPPAGE)
    out["fixed20_relative50bp_proxy"]=out.fixed20_net50bp_proxy-out.benchmark_fixed20
    out.loc[~out.full20_quote_complete,"fixed20_relative50bp_proxy"]=np.nan
    out["barrier_evaluable"]=out.outcome.ne("censored")
    out["fixed20_evaluable"]=out.full20_quote_complete & out.benchmark_fixed20.notna()
    return out


def evaluate(out: pd.DataFrame) -> tuple[pd.DataFrame,pd.DataFrame]:
    # Same stock-days for every ranking, both labels and the fixed horizon.
    accepted=out[out.barrier_evaluable & out.fixed20_evaluable].copy()
    assert len(accepted)>300_000
    daily=[]
    for date,frame in accepted.groupby("date",sort=True):
        k=math.ceil(.1*len(frame))
        target=frame.outcome.eq("target")
        row=dict(date=str(date.date()),year=date.year,eligible=len(frame),
                 top_n=k,base_target_rate=float(target.mean()),
                 population_fixed20_relative=float(frame.fixed20_relative50bp_proxy.mean()))
        for m in METHODS:
            selected=frame.sort_values([m,"symbol"],ascending=[False,True]).head(k)
            row[m+"_target_rate"]=float(selected.outcome.eq("target").mean())
            row[m+"_barrier_net50bp"]=float(selected.barrier_net50bp_proxy.mean())
            row[m+"_fixed20_relative50bp"]=float(
                selected.fixed20_relative50bp_proxy.mean())
        daily.append(row)
    daily=pd.DataFrame(daily)
    summary=[]
    for year,g in daily.groupby("year"):
        base=float(g.base_target_rate.mean())
        for m in METHODS:
            hit=float(g[m+"_target_rate"].mean())
            summary.append(dict(year=year,method=m,dates=len(g),
                                eligible_stock_days=int(g.eligible.sum()),
                                base_target_rate=base,target_rate_top10=hit,
                                target_lift=hit/base,
                                top10_barrier_net50bp=float(g[m+"_barrier_net50bp"].mean()),
                                top10_fixed20_relative50bp=float(
                                    g[m+"_fixed20_relative50bp"].mean()),
                                population_fixed20_relative50bp=float(
                                    g.population_fixed20_relative.mean())))
    return daily,pd.DataFrame(summary)


def main():
    OUT.mkdir(exist_ok=True)
    out=assemble_outcomes()
    daily,summary=evaluate(out)
    audit=out.groupby("fold_year",as_index=False).agg(
        total=("symbol","size"),barrier_evaluable=("barrier_evaluable","sum"),
        fixed20_evaluable=("fixed20_evaluable","sum"),
        ambiguous_both=("both_barriers_same_day","sum"))
    audit.to_csv(OUT/"entry_barrier_coverage_v80.csv",index=False)
    daily.to_csv(OUT/"entry_barrier_daily_v80.csv",index=False)
    summary.to_csv(OUT/"entry_barrier_summary_v80.csv",index=False)
    params=dict(entry="next market day adjusted open",horizon_market_days=HORIZON,
                target=UP,stop=DOWN,same_day_both="stop_first",future_gap="exit_at_open",
                intraday_cross="barrier_price_proxy",fees_each_side=FEE,
                sell_tax=TAX,slippage_each_side=SLIPPAGE,
                min_broker_fee_included=False,
                fill_and_share_entitlement_verified=False,
                independently_untouched=False)
    (OUT/"entry_barrier_config_v80.json").write_text(json.dumps(params,indent=2)+"\n")
    print(audit.to_string(index=False))
    print(summary.to_string(index=False))


if __name__=="__main__":
    main()
