"""Bounded accounting attribution on exact frozen TWSE daily research outputs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import numpy as np
import pandas as pd

from research_runtime import atomic_json, sha256, utcnow

CONFIG=Path('configs/research_reassessment_20261016.json')
ROOT=Path('inputs/reassessment_20261016')
OUT=Path('deliverables/reassessment_20261016')


def verified_bundle(path, expected):
    if sha256(path)!=expected:raise ValueError('Frozen archive hash differs')
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None or len(z.namelist())!=len(set(z.namelist())):
            raise ValueError('Archive CRC/duplicate member failure')
        manifest=json.loads(z.read('SHA256MANIFEST.json'))
        for name,digest in manifest.items():
            if Path(name).is_absolute() or '..' in Path(name).parts or hashlib.sha256(z.read(name)).hexdigest()!=digest:
                raise ValueError('Frozen member hash/path differs: '+name)
        return manifest


def restore():
    c=json.loads(CONFIG.read_text())['attribution'];ROOT.mkdir(parents=True,exist_ok=True)
    original=Path(c['archive']);manifest=verified_bundle(original,c['archive_sha256'])
    backup=ROOT/'backup'/'original_bundle.zip';backup.parent.mkdir(exist_ok=True)
    shutil.copyfile(original,backup)
    retrieved=ROOT/'original_bundle.retrieved.zip';shutil.copyfile(backup,retrieved)
    verified_bundle(retrieved,c['archive_sha256'])
    with zipfile.ZipFile(retrieved) as z:body=z.read(c['price_member'])
    if hashlib.sha256(body).hexdigest()!=c['price_sha256'] or manifest[c['price_member']]!=c['price_sha256']:
        raise ValueError('Frozen price input differs')
    (ROOT/'prices.csv.gz').write_bytes(body)
    for path,digest in c['inputs'].items():
        if sha256(path)!=digest:raise ValueError('Frozen daily input differs: '+path)
    atomic_json(OUT/'source_receipt.json',dict(status='passed',verified_at=utcnow(),source_archive_sha256=c['archive_sha256'],manifest_files=len(manifest),price_sha256=c['price_sha256'],backup_path=str(backup),retrieved_path=str(retrieved),roundtrip_verified=True,crc_verified=True,daily_inputs=c['inputs'],storage='local persistent backup; same filesystem, no off-host disaster recovery'))


def decompose(selected_net_relative,pool_net_relative,benchmark,fee,tax,slip):
    if any(not np.isfinite(v) or v<0 or v>=1 for v in (fee,tax,slip)) or fee+tax>=1:
        raise ValueError('Invalid frozen costs')
    selected,pool,b=np.broadcast_arrays(np.asarray(selected_net_relative,dtype=float),np.asarray(pool_net_relative,dtype=float),np.asarray(benchmark,dtype=float))
    if not np.isfinite(selected).all() or not np.isfinite(pool).all() or not np.isfinite(b).all():
        raise ValueError('Attribution requires matched finite daily endpoints')
    a=(1-slip)*(1-fee-tax)/((1+slip)*(1+fee))
    selected_gross=(selected+b+1)/a-1
    pool_gross=(pool+b+1)/a-1
    if (selected_gross < -1-1e-12).any() or (pool_gross < -1-1e-12).any():
        raise ValueError('Impossible gross return')
    selection=selected_gross-pool_gross
    universe=pool_gross-b
    cost=selected_gross-(selected+b)
    residual=selection+universe-cost-selected
    if np.abs(residual).max(initial=0)>1e-12:raise ValueError('Attribution identity failed')
    return selection,universe,cost,residual


def attribution():
    c=json.loads(CONFIG.read_text())['attribution'];receipt=json.loads((OUT/'source_receipt.json').read_text())
    price=ROOT/'prices.csv.gz'
    if not receipt['roundtrip_verified'] or sha256(price)!=c['price_sha256']:raise ValueError('Unverified frozen source')
    days=set();pieces=[]
    for f in pd.read_csv(price,usecols=['date','symbol','adj_open','adj_close'],dtype={'symbol':str},chunksize=200000):
        days.update(f.date.unique());pieces.append(f[f.symbol.eq('0050')])
    clock=pd.DatetimeIndex(sorted(days));benchmark=pd.concat(pieces,ignore_index=True);benchmark['date']=pd.to_datetime(benchmark.date)
    if benchmark.date.duplicated().any():raise ValueError('Duplicate benchmark date')
    b=benchmark.set_index('date').reindex(clock)
    complete=b.adj_close.where(b.adj_close.gt(0)).shift(-1).iloc[::-1].rolling(c['horizon'],min_periods=c['horizon']).count().iloc[::-1].eq(c['horizon'])
    benchmark_return=(b.adj_close.shift(-c['horizon'])/b.adj_open.shift(-1)-1).where(complete&b.adj_open.shift(-1).gt(0)&b.adj_close.shift(-c['horizon']).gt(0))
    summaries=[];daily=[]
    for year in c['years']:
        path=Path(f'deliverables/institutional_increment_daily_{year}.csv');meta_path=Path(f'deliverables/institutional_increment_summary_{year}.json')
        if any(sha256(p)!=c['inputs'][str(p)] for p in (path,meta_path)):raise ValueError('Daily input drift')
        meta=json.loads(meta_path.read_text());cfg=meta['config'];f=pd.read_csv(path,parse_dates=['date'])
        if meta['input_sha256']['prices']!=c['price_sha256'] or f.date.duplicated().any() or not f.date.dt.year.eq(year).all():raise ValueError('Study scope/price hash differs')
        bm=f.date.map(benchmark_return)
        if bm.isna().any():raise ValueError('Saved study has unknown benchmark endpoints')
        for method in c['methods']:
            column=method+'_top_net_relative';selection,universe,cost,residual=decompose(f[column],f.pool_net_relative,bm,cfg['commission'],cfg['sell_tax'],cfg['slippage_each_side'])
            if not np.isclose(f[column].mean(),meta['daily_mean_metrics'][column],rtol=0,atol=1e-12):raise ValueError('Saved summary differs')
            rows=pd.DataFrame(dict(date=f.date.dt.strftime('%Y-%m-%d'),year=year,method=method,pool=f.pool,selected=f.top_count,net_selected_minus_0050=f[column],gross_selection_minus_pool=selection,gross_pool_minus_0050=universe,selected_cost_drag=cost,identity_residual=residual))
            daily.append(rows)
            summaries.append(dict(year=year,method=method,dates=len(f),net_selected_minus_0050=float(f[column].mean()),gross_selection_minus_pool=float(selection.mean()),gross_pool_minus_0050=float(universe.mean()),selected_cost_drag=float(cost.mean()),max_identity_error=float(np.abs(residual).max())))
    pd.concat(daily,ignore_index=True).to_csv(OUT/'daily_attribution.csv',index=False)
    atomic_json(OUT/'summary.json',dict(status='completed_bounded_attribution',observed_at=utcnow(),scope=c['scope'],config_sha256=sha256(CONFIG),price_sha256=c['price_sha256'],summary=summaries,limitations=['Conditional on the original study future-complete pool, not a newly reconstructed as-of universe','Equal daily and equal selected-stock weights; overlapping 20-day quote windows are not portfolio NAV','Benchmark ETF costs remain excluded as frozen; cost drag is a return-dependent accounting term','Only TWSE institutional study restored; TPEx common matrices and stock selections unavailable locally; no substituted data','No refitting or threshold search; descriptive identity is not causal identification']))
    lines=['# 有限失敗歸因：上市法人20日研究','','使用與原報告SHA完全相符的凍結價格與逐日結果，沒有重新下載或更換歷史輸入。每個方法在同日、相同等權口徑拆解：','','**股票扣成本相對0050 = 選股毛報酬相對同池 + 同池毛報酬相對0050 − 選股成本拖累**。','','| 年 | 方法 | 已知日 | 扣成本相對0050 | 選股相對同池（毛） | 同池相對0050（毛） | 成本拖累 |','|---|---|---:|---:|---:|---:|---:|']
    for r in summaries:lines.append(f'| {r["year"]} | {r["method"]} | {r["dates"]} | {r["net_selected_minus_0050"]*100:+.3f} | {r["gross_selection_minus_pool"]*100:+.3f} | {r["gross_pool_minus_0050"]*100:+.3f} | {r["selected_cost_drag"]*100:.3f} |')
    lines+=['','單位為百分點；各欄為同一組逐日窗口的平均，不能累加為年報酬。等式逐日殘差小於1e-12。成本沿用原研究，包含手續費、稅與假設滑價；不是實際成交成本。','','此舊法人研究先要求未來報價完整才進池，歸因只對這個條件池成立，不外推至上櫃七法或完整當時股票池。此輪只選擇可恢復精確輸入的研究，未挑選結果最好年份。TPEx完整矩陣缺失另列，不以新資料替代。']
    lines += ['', '## 本輪判讀', '',
              '三年度共同池未扣成本就落後0050約2.07～2.91個百分點；成本再拖累約1.58～1.65個百分點。這是每日重疊20日窗口的條件平均，不是年度費用或年度損失。',
              '量價與法人模型相對同池的選股毛增量介於約−0.44～+0.50個百分點，跨年不穩定；2026即使選股高於同池，也不足以抵消池與成本的落差。波動排序在2025／2026對同池有正增量，但整體仍落後原0050口徑。',
              '這份會計拆解支持先釐清目標與可用資訊，再考慮新模型；它沒有識別股票池落後的因果機制，沒有排除產業／規模／風險曝險，也沒有證明換一個基準或改選股池就能獲利。',
              '一次性歸因至此完成；七規則每日計畫維持停止。新的營運研究另以原始公告版本、時間及簡單預測基準作資料試點，不延長這條舊研究。']
    (OUT/'report.md').write_text('\n'.join(lines)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['restore','attribution']);a=p.parse_args();restore() if a.stage=='restore' else attribution()
