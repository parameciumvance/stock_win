"""Serial replay of preserved quarterly guidance; no new HTTP or raw copies."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from research_runtime import atomic_json,sha256,utcnow
from operating_snapshot_sources import SnapshotSources

ROOT=Path('inputs/operating_guidance_20261018')
OUT=Path('deliverables/operating_guidance_20261018')
PRIOR=Path('deliverables/operating_replan_20261018')
PROTOCOL=Path('configs/operating_guidance_protocol_20261018.json')
FROZEN_PROTOCOL='03f4d65db73ab4ad0a9c6bce2d34cbbba5a22b5ac94b96a947f782dd596e2ef1'


def protocol():
    if sha256(PROTOCOL)!=FROZEN_PROTOCOL:raise ValueError('Guidance protocol drift')
    p=json.loads(PROTOCOL.read_text())
    if sha256(Path('configs/operating_snapshot_protocol_20261018.json'))!=p['snapshot_protocol_sha256']:raise ValueError('Snapshot protocol drift')
    return p


def load_panel():
    rows=list(csv.DictReader((PRIOR/'panel.csv').open()))
    for row in rows:
        for key in ['gross_margin_pct','eps_twd','revenue_twd_billions']:row[key]=float(row[key])
        for key in ['ready_for_historical_model','accounting_standard_explicit']:
            if row[key] not in {'True','False'}:raise ValueError('Invalid panel boolean')
            row[key]=row[key]=='True'
    return rows


def verify_inputs():
    p=protocol();OUT.mkdir(parents=True,exist_ok=True);state=json.loads((PRIOR/'pipeline_state.json').read_text())
    outputs=state['stages']['audit']['outputs']
    for name in ['panel.csv','arithmetic_errors.csv','arithmetic_summary.json','source_inventory.json']:
        path=PRIOR/name
        if sha256(path)!=outputs[str(path)]:raise ValueError('Frozen derived snapshot output drift: '+name)
    source=SnapshotSources(PRIOR,p['raw_checkpoint_sha256'])
    if hashlib.sha256(source.top['new_protocol.json']).hexdigest()!=p['snapshot_protocol_sha256']:raise ValueError('Archived snapshot policy differs')
    expected={(i,q) for i in p['issuers'] for q in p['origin_quarters']}
    if len(source.selected)!=len(expected) or {(s['issuer'],s['quarter']) for s in source.selected}!=expected:raise ValueError('Raw source cohort mismatch')
    documents=[]
    for s in source.selected:
        d=source.document(s);documents.append({k:v for k,v in d.items() if k!='body'})
    atomic_json(OUT/'inputs_receipt.json',dict(verified_at=utcnow(),raw_archive_sha256=source.receipt['sha256'],
        raw_archive_reused=True,new_raw_downloads=0,new_raw_archive_copies=0,
        previous_backup_path=source.transfer['backup_path'],previous_transfer_receipt=str(source.receipt['transfer_receipt']),
        sha_manifest_crc_verified=True,guidance_protocol_sha256=sha256(PROTOCOL),snapshot_protocol_sha256=p['snapshot_protocol_sha256'],
        source_documents=documents,panel_sha256=sha256(PRIOR/'panel.csv')))


def replay():
    from pypdf import PdfReader
    from operating_snapshot import extract_financials
    from operating_guidance import extract_guidance
    p=protocol();source=SnapshotSources(PRIOR,p['raw_checkpoint_sha256']);panel={(r['issuer'],r['quarter']):r for r in load_panel()}
    records=[];value_checks=0
    for s in source.selected:
        d=source.document(s);reader=PdfReader(io.BytesIO(d['body']));pages=[page.extract_text() for page in reader.pages]
        numbers=extract_financials(pages[0],issuer=d['issuer'],quarter=d['quarter'],management=d['management'])
        prior=panel[(d['issuer'],d['quarter'])]
        if prior['source_sha256']!=d['sha256']:raise ValueError('Snapshot source replaced')
        for key in ['gross_margin_pct','eps_twd','revenue_twd_billions']:
            if numbers[key]!=prior[key]:raise ValueError('Numeric replay changed: '+d['issuer']+' '+d['quarter']+' '+key)
            value_checks+=1
        guidance=extract_guidance(pages,d['issuer'],d['quarter'])
        guidance.update(source_sha256=d['sha256'],source_url=d['url'],document_pages=len(pages),
            visible_document_date=numbers['visible_document_date'],source_observed_at=d['observed_at'],
            accounting_standard_explicit=numbers['accounting_standard_explicit'])
        records.append(guidance)
    atomic_json(OUT/'guidance_records.json',dict(records=records,source_checkpoint_sha256=source.receipt['sha256'],ready_for_historical_model=False))
    atomic_json(OUT/'source_replay_checks.json',dict(documents_verified=len(records),financial_values_replayed=value_checks,all_values_match_previous_panel=True,passed=True))


def compare():
    from operating_guidance import compare as compare_guidance
    p=protocol();records=json.loads((OUT/'guidance_records.json').read_text())['records']
    rows,summary=compare_guidance(load_panel(),records,p)
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with (OUT/'comparison.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');w.writeheader();w.writerows(rows)
    atomic_json(OUT/'summary.json',dict(summary,origin_documents=len(records),origin_guidance_unavailable=sum(r['kind']=='unavailable' for r in records),
        conditions_note='Realized values compared with stated intervals; FX/other assumptions not verified; not a test of conditional forecast skill',
        metrics_note='Outside-interval distance is not point MAE; interval width reduces distance mechanically',
        raw_checkpoint_sha256=p['raw_checkpoint_sha256'],guidance_protocol_sha256=sha256(PROTOCOL)))


def render_review(rows):
    from html import escape
    from urllib.parse import urlsplit
    items=[]
    for row in rows:
        url=row['guidance_source_url']
        if urlsplit(url).scheme!='https':raise ValueError('Unsafe source link')
        fmt=lambda v:'—' if v is None else str(v)
        statement=row['guidance_statement'] or '無可用財測原句'
        if row.get('assumed_fx_twd_per_usd') is not None:statement+='〔匯率假設：1 USD = '+str(row['assumed_fx_twd_per_usd'])+' TWD；未核實是否成真〕'
        cells=[row['issuer'],row['origin_quarter']+' → '+row['target_quarter'],statement,fmt(row['actual_gross_margin_pct']),row['direction'] or '未評分',fmt(row['distance_pp'])]
        source='<a href="'+escape(url,quote=True)+'#page='+str(row['guidance_page'] or 1)+'">PDF p.'+str(row['guidance_page'] or '?')+'</a><small>SHA '+escape(row['guidance_source_sha256'])+'</small>'
        items.append('<tr data-issuer="'+escape(row['issuer'])+'" data-scored="'+str(row['finite_interval_diagnostics_eligible']).lower()+'">'+''.join('<td>'+escape(str(v))+'</td>' for v in cells)+'<td>'+source+'</td></tr>')
    return '''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>財測與實際值核對</title>
<style>body{font:16px system-ui;max-width:1400px;margin:28px auto;padding:0 18px;color:#17202a}p{line-height:1.6}table{border-collapse:collapse;width:100%}th,td{padding:12px;border-bottom:1px solid #ccd1d1;text-align:left;vertical-align:top}th{background:#edf2f7}small{display:block;font:11px monospace;overflow-wrap:anywhere;max-width:200px;color:#566573}select,input{font:inherit;margin:8px;padding:6px}tr[hidden]{display:none}</style>
<h1>管理層財測與實際值核對</h1><p>既有選用版本的回顧對照。明確區間才計算落點／超出幅度；約數、模糊範圍及帶條件下界不混入區間統計。所有首次公開／歷史建模資格仍未驗證。</p>
<label>公司<select id="issuer"><option value="all">全部</option><option value="2330">台積電</option><option value="2303">聯電</option></select></label>
<label>資料<select id="scored"><option value="all">全部</option><option value="true">明確區間</option><option value="false">未量化評分</option></select></label><label>搜尋<input id="query" placeholder="季度或原句"></label>
<p id="count" aria-live="polite"></p><table><thead><tr><th>公司</th><th>文件季 → 目標季</th><th>財測原句（空白正規化）</th><th>實際毛利率%</th><th>落點</th><th>超出百分點</th><th>來源</th></tr></thead><tbody>'''+''.join(items)+'''</tbody></table><p>台積電的原財測含匯率假設；未驗證假設是否成真。落在區間內並非宣稱預測有效；區間距離與點預測MAE不能直接比較。資料與證據來自已封存PDF，頁面本身不發送任何資料請求。</p><script>
const issuer=document.querySelector('#issuer'),scored=document.querySelector('#scored'),query=document.querySelector('#query');
function filter(){let n=0;for(const row of document.querySelectorAll('tbody tr')){row.hidden=!(issuer.value==='all'||row.dataset.issuer===issuer.value)||!(scored.value==='all'||row.dataset.scored===scored.value)||!row.textContent.toLowerCase().includes(query.value.toLowerCase());if(!row.hidden)n++;}document.querySelector('#count').textContent=`顯示 ${n} / ${document.querySelectorAll('tbody tr').length} 列`;}
for(const node of [issuer,scored,query])node.addEventListener('input',filter);filter();</script></html>'''


def report():
    from operating_guidance import compare as compare_guidance
    p=protocol();records=json.loads((OUT/'guidance_records.json').read_text())['records'];rows,computed=compare_guidance(load_panel(),records,p)
    summary=json.loads((OUT/'summary.json').read_text())
    if computed['results']!=summary['results']:raise ValueError('Summary changed before report')
    (OUT/'review.html').write_text(render_review(rows))
    atomic_json(OUT/'next_tasks.json',dict(status='guidance_source_replay_and_descriptive_comparison_completed',manual_download_requests=[],
        completed=['24 origin documents reread; numeric values and PDF hashes unchanged','16 target rows kept with page-linked guidance evidence','finite intervals separated from qualitative/conditional bounds','offline searchable source-review artifact generated'],
        conclusion='Useful source-review/extraction tool. This cohort does not establish forecast skill or support a new stock model/year-long manual validation plan.',
        no_external_dependency_for_this_run=True,seven_rule_daily_plan='stopped_by_user_no_resume'))
    atomic_json(OUT/'pilot_decision.json',dict(decision='Complete the bounded operating-data/source pilot for research-tool use; do not promote it to a stock model',basis=['Both issuers fixed 12-quarter numeric/source replay completed','All 16 target-quarter guidance comparisons retained','One issuer provides eight numeric intervals; the other provides no eight comparable finite intervals','Exact historical information sets and independent forecast skill remain unverified'],next_action='Retain the automated extraction and source-review tool. Do not keep extending this cohort, retrying blocked sources, or requesting user downloads to claim predictive advantage.',models_to_fit_under_this_pilot=0,manual_validation_plan_to_start=False,original_seven_rule_plan='stopped_by_user_no_resume'))
    table='\n'.join('| '+r['issuer']+' | '+r['target_quarter']+' | '+(str(r['lower_pct'])+'–'+str(r['upper_pct']) if r['guidance_kind']=='closed_interval' else r['guidance_statement'])+' | '+str(r['actual_gross_margin_pct'])+' | '+(r['direction'] or '未納入區間統計')+' | '+('—' if r['distance_pp'] is None else str(r['distance_pp']))+' |' for r in rows)
    tsmc=next(r for r in summary['results'] if r['issuer']=='2330');umc=next(r for r in summary['results'] if r['issuer']=='2303')
    (OUT/'report.md').write_text(f'''# 管理層財測與實際值：來源重播及描述性對照

本輪沒有下載新資料，重用已備份取回的原始包SHA `{p['raw_checkpoint_sha256']}`。原24季面板、兩份凍結2024Q4原文與既有算術結果未修改；新協定只固定原句擷取、下一季對齊與區間診斷，不擬合模型或調整規則。24份文件重新解析，72個毛利率／EPS／營收值與既有面板一致，來源SHA／manifest／CRC均驗證。

## 得到什麼

台積電2024Q1～2025Q4八個目標皆有上一季文件的明確區間：**{tsmc['contained']}/8落在區間內、{tsmc['above']}/8高於上界、{tsmc['below']}/8低於下界**。平均列印區間寬度{tsmc['mean_printed_width_pp']:.1f}百分點，平均超出區間距離{tsmc['mean_outside_distance_pp']:.3f}百分點。這是已選用版本的實際落點描述，不是獨立預測檢定。

聯電八個目標保留全部原句，有限數字區間{umc['finite_intervals']}個，未評分{umc['unscored_targets']}個。「約30%」「三成中段」「接近30%」沒有明定容許範圍，不能自行改成點預測或上下界。2025Q1的「高於25%、含0121地震影響」保留嚴格下界與條件；實際26.7%在算術上大於25%，但不納入有限區間統計，也不宣稱條件已驗證。2025Q3的「約Q2毛利率，取決於匯率」亦不改成前季點預測。

| 公司 | 目標季 | 原財測區間／原句 | 實際毛利率% | 落點 | 超出百分點 |
|---|---|---|---:|---|---:|
{table}

[離線可搜尋核對頁](review.html)可依公司、是否明確區間及文字篩選，連回原PDF頁碼與SHA；頁面本身沒有下載或傳送資料的程式。完整24份原句與匯率條件在[guidance_records.json](guidance_records.json)，16列對照在[comparison.csv](comparison.csv)。

## 為何不能直接宣稱優勢

區間距離不是點預測MAE；擴大區間就能機械式減少區間距離，因此不能把{tsmc['mean_outside_distance_pp']:.3f}與前輪台積電上一季基準MAE1.263直接相減、宣稱管理層預測勝出。原財測的美元兌台幣假設已保存，實際匯率條件是否成真未驗證；落點只是事後數字對照，非條件預測效力判斷。

本批是本次選用版本，完整歷史版本／首次公開時點未核實；只有兩家公司、每家八個目標。全部ready_for_historical_model=False、forecast_skill_established=False。管理報告未明示TIFRS的舊標記保持；本輪沒有將其補造為明示準則。

## 工作方向

已把資料工具從三個財務值擷取推進到可查原句、目標季、條件、PDF頁碼的財測核對。固定小型來源試點已完成資料工具用途的驗收；本輪[投入決定](pilot_decision.json)是保留自動核對工具，不再為此小樣本延伸下載或調整模型。現有結果不支持升級股票模型或恢復一年每日人工驗證。此輪無外部資料依賴、無人工補件。七規則每日計畫保持停止，未產生新有效前瞻訊號、訂單或績效宣稱。

檢查入口：[來源重播](source_replay_checks.json)、[輸入重用收據](inputs_receipt.json)、[測試](tests.json)、[階段hash](pipeline_state.json)、[目前待辦](next_tasks.json)。
''')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['verify_inputs','replay','compare','report']);globals()[parser.parse_args().stage]()
