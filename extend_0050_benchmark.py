"""Join pinned forward-price benchmark segments on a common causal scale."""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd
from tpex_rule_comparison import EXPECTED

def main():
    root=Path('deliverables/benchmark_2022_extended');root.mkdir(parents=True,exist_ok=True)
    first=Path('deliverables/benchmark_2022/prices_adjusted_2022.csv.gz');later=Path('benchmark_restore/prices_adjusted_2023_2026.csv.gz')
    meta=json.loads(first.with_name('summary.json').read_text());assert hashlib.sha256(first.read_bytes()).hexdigest()==meta['sha256'];assert hashlib.sha256(later.read_bytes()).hexdigest()==EXPECTED
    a=pd.read_csv(first,dtype={'symbol':str});b=pd.read_csv(later,dtype={'symbol':str});b=b[b.symbol.eq('0050')].copy().sort_values('date');a=a.sort_values('date')
    assert not a.date.duplicated().any() and not b.date.duplicated().any() and a.date.max()<b.date.min()
    assert b.causal_factor.iloc[0]==1 and np.allclose(b.adj_open,b.open*b.causal_factor) and np.allclose(b.adj_close,b.close*b.causal_factor)
    scale=float(a.adj_close.iloc[-1]/a.close.iloc[-1]);b[['adj_open','adj_close']]*=scale
    columns=['date','symbol','open','close','adj_open','adj_close'];out=pd.concat([a[columns],b[columns]],ignore_index=True);path=root/'prices_adjusted_2022_2026.csv.gz';out.to_csv(path,index=False,compression={'method':'gzip','mtime':0})
    summary={'rows':len(out),'source_hashes':{str(first):meta['sha256'],str(later):EXPECTED},'continuation_scale':scale,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'method':'2022 theoretical cash-dividend proxy joined to pinned 2023-2026 forward causal proxy; not backward adjusted','limitations':['not cash ledger or fills','2022 complete corporate-action audit pending']};(root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
if __name__=='__main__':main()
