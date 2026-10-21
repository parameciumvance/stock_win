"""Independently check the two pinned current indices and their Q3 overlap.

JSON rows and detail-pointer identities are checked without production parsers.
The reused independent helper verifies saved ZIP/transport bytes only. No notice
body, quote source, current transaction state or contractual right is inferred.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from cash_merger_census_independent import _readback, _transport


OUT = Path("deliverables/cash_merger_current_20261021")
POLICY = Path("configs/cash_merger_current_protocol_20261021.json")
ARCHIVE_SHA256 = "8b5174da2086dbb7de6f02b884f0c858e958abbfc5581f7c18d0ecf7b6c270ea"
Q3_SHA256 = "b88d784df93af2f092df0a14208997e823232034b4ef636fcc9c6e9e7e4f588a"
FIELDS = {"CDATE", "COMPANY_NAME", "AN_NAME", "CODE_NAME", "AN_CODE",
          "CTIME", "TYPEK", "SUBJECT", "HYPERLINK", "COMPANY_ID"}
QUERIES = (("target_6674_m00.json", "6674", 7), ("buyer_2324_m00.json", "2324", 2))
START, END = "2026-09-18", "2026-10-21"


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(body):
    return hashlib.sha256(body).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Nonfinite JSON constant: " + value)


def _finite(value):
    number = float(value)
    require(math.isfinite(number), "Nonfinite JSON float")
    return number


def strict_json(body):
    return json.loads(body.decode("utf-8-sig", errors="strict"),
                      object_pairs_hook=_unique, parse_constant=_reject_constant,
                      parse_float=_finite)


def _row(original, issuer, start, end):
    require(isinstance(original, dict) and set(original) == FIELDS,
            "Changed complete original field schema")
    require(all(isinstance(v, str) and v for v in original.values()), "Empty/nontext source field")
    require(original["COMPANY_ID"] == issuer and re.fullmatch(r"[0-9]{4,6}", issuer),
            "Wrong issuer")
    require(re.fullmatch(r"M[0-9]{2}", original["AN_CODE"]), "Invalid reported category")
    require(re.fullmatch(r"[0-9]{3}/[0-9]{2}/[0-9]{2}", original["CDATE"]), "Invalid ROC date")
    y, m, d = map(int, original["CDATE"].split("/"))
    day = datetime(y + 1911, m, d).date().isoformat()
    require(start <= day <= end, "Date outside fixed query")
    clock = original["CTIME"]
    require(re.fullmatch(r"[0-9]{2}:[0-9]{2}:[0-9]{2}", clock), "Invalid reported clock")
    datetime.strptime(clock, "%H:%M:%S")
    url = urlparse(original["HYPERLINK"])
    require(url.scheme == "https" and url.netloc == "mopsov.twse.com.tw"
            and url.path == "/mops/web/ajax_t05sr01_1" and not url.fragment,
            "Nonofficial original URL")
    query = parse_qs(url.query, keep_blank_values=True)
    require(set(query) == {"firstin", "stp", "step", "SEQ_NO", "SPOKE_TIME", "SPOKE_DATE", "COMPANY_ID"}
            and all(len(v) == 1 for v in query.values()), "Ambiguous original URL identity")
    require(query["firstin"] == ["true"] and query["stp"] == ["1"] and query["step"] == ["1"],
            "Changed detail routing")
    require(re.fullmatch(r"[1-9][0-9]*", query["SEQ_NO"][0]), "Invalid sequence")
    url_clock = query["SPOKE_TIME"][0]
    require(re.fullmatch(r"[0-9]{1,6}", url_clock), "Invalid URL clock")
    require(query["COMPANY_ID"] == [issuer] and query["SPOKE_DATE"] == [day.replace("-", "")]
            and url_clock.zfill(6) == clock.replace(":", ""), "URL/report identity mismatch")
    pointer = f'{issuer}:{day}:{clock.replace(":", "")}:{query["SEQ_NO"][0]}'
    return dict(event_id=original["AN_CODE"] + ":" + pointer, pointer_identity=pointer,
                issuer=issuer, reported_datetime=day + "T" + clock + "+08:00",
                reported_category=original["AN_CODE"], original_fields=original)


def parse_saved_index(body: bytes, issuer: str, start=START, end=END) -> dict:
    require(datetime.strptime(start, "%Y-%m-%d") <= datetime.strptime(end, "%Y-%m-%d"),
            "Reversed date range")
    payload = strict_json(body)
    require(isinstance(payload, dict) and {"data", "message", "status"} <= set(payload)
            and not set(payload) - {"data", "message", "status", "total"}, "Unexpected index response schema")
    require(payload["status"] == "success" and payload["message"] == ["回傳成功"], "Non-success response")
    raw_rows = payload["data"]
    require(isinstance(raw_rows, list) and len(raw_rows) < 1000, "Row ceiling or invalid data")
    total = payload.get("total")
    if "total" in payload:
        require(type(total) is int and total == len(raw_rows) and 0 <= total < 1000, "Declared total mismatch")
    rows = [_row(original, issuer, start, end) for original in raw_rows]
    pointers = [row["pointer_identity"] for row in rows]
    require(len(set(pointers)) == len(pointers), "Duplicate pointer, including across categories")
    return dict(body_sha256=digest(body), rows=rows, declared_total=total,
                count_reconciliation_passed="total" in payload,
                all_categories_preserved=True, complete_population_verified=False,
                current_transaction_status_verified=False, contractual_cash_claim_verified=False)


def reconcile_q3(current_rows: list[dict], quarter_body: bytes) -> list[dict]:
    payload = strict_json(quarter_body)
    require(set(payload) == {"data", "status", "message"} and payload["status"] == "success"
            and payload["message"] == ["回傳成功"] and isinstance(payload["data"], list),
            "Q3 index response schema/status differs")
    index = {}
    for original in payload["data"]:
        row = _row(original, original["COMPANY_ID"], "2026-07-01", "2026-09-30")
        require(row["reported_category"] == "M11", "Q3 M11 category changed")
        pointer = row["pointer_identity"]
        require(pointer not in index, "Duplicate Q3 pointer")
        index[pointer] = original
    matches = []
    for row in current_rows:
        if row["pointer_identity"] in index:
            require(row["original_fields"] == index[row["pointer_identity"]],
                    "Q3/current complete original fields changed")
            matches.append(row)
    return matches


def audit(root: Path | str) -> dict:
    root = Path(root)
    policy_body = (root / POLICY).read_bytes()
    policy = strict_json(policy_body)
    require(digest(policy_body) == strict_json((root / OUT / "protocol_freeze.json").read_bytes())["protocol_sha256"],
            "Frozen current protocol drift")
    for filename, expected in policy["prior_checkpoints"].items():
        body = (root / filename).read_bytes()
        require(digest(body) == expected, "Prior checkpoint drift")
        for name, wanted in strict_json(body)["files"].items():
            require(digest((root / name).read_bytes()) == wanted, "Prior frozen member drift")
    current, archive = _readback(root, OUT, "index", ARCHIVE_SHA256)
    require(current["protocol.json"] == policy_body and archive["manifest_files"] == 9,
            "Archived current protocol/member count differs")
    request_ref = policy["batches"]["index"]
    request_body = (root / request_ref["path"]).read_bytes()
    require(digest(request_body) == request_ref["sha256"] and current["requests.json"] == request_body,
            "Archived current request configuration differs")
    requests = strict_json(request_body)["requests"]
    require(len(requests) == 2 and {r["filename"] for r in requests} == {q[0] for q in QUERIES},
            "Current request population differs")
    for request in requests:
        issuer = {q[0]: q[1] for q in QUERIES}[request["filename"]]
        require(request["url"] == "https://mopsov.twse.com.tw/mops/web/ezsearch_query"
                and request["method"] == "POST", "Unexpected issuer query route")
        data = parse_qs(request["data"], keep_blank_values=True)
        require(all(len(v) == 1 for v in data.values()) and data == {
            "step": ["00"], "RADIO_CM": ["2"], "TYPEK": [""], "CO_MARKET": [""],
            "CO_ID": [issuer], "PRO_ITEM": ["M00"], "SUBJECT": [""], "SDATE": ["115/09/18"],
            "EDATE": ["115/10/21"], "lang": ["TW"], "AN": [""]}, "Frozen issuer/range query differs")
    _transport(current, {q[0] for q in QUERIES})
    q3, q3_archive = _readback(root, Path("deliverables/cash_merger_20261021"), "discovery", Q3_SHA256)
    quarter_body = q3["raw/m11_2026q3.json"]
    require(len(strict_json(quarter_body)["data"]) == 476, "Frozen Q3 count differs")
    rows, indices = [], []
    for filename, issuer, expected_count in QUERIES:
        index = parse_saved_index(current["raw/" + filename], issuer)
        require(len(index["rows"]) == expected_count, "Pinned issuer row count differs")
        rows.extend(index.pop("rows"))
        indices.append(dict(filename=filename, issuer=issuer, returned_rows=expected_count, **index))
    matches = reconcile_q3(rows, quarter_body)
    require(len(matches) == 2 and {r["issuer"] for r in matches} == {"6674", "2324"},
            "Pinned Q3/current overlap differs")
    match_ids = {r["event_id"] for r in matches}
    observations = []
    for record in strict_json(current["raw/results.json"])["requests"]:
        started = datetime.fromisoformat(record["request_started_at"])
        observed = datetime.fromisoformat(record["observed_at"])
        require(started.utcoffset() is not None and observed.utcoffset() is not None and observed >= started,
                "Invalid actual observation timestamp")
        observations.append(dict(filename=record["request"]["filename"],
                                 request_started_at=record["request_started_at"], observed_at=record["observed_at"],
                                 observed_taipei=observed.astimezone(ZoneInfo("Asia/Taipei")).isoformat()))
    canonical = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode("utf-8")
    return dict(
        scope="Independent saved M00 index identity and full-field Q3 overlap audit; no new notice originals or transaction-status inference.",
        auditor_script_sha256=digest(Path(__file__).read_bytes()),
        protocol_sha256=digest(policy_body), requests_sha256=digest(request_body),
        archive=archive, q3_archive=q3_archive, observations=observations,
        query_start=START, query_end=END, query_category="M00", index_results=indices,
        total_returned_rows=9, all_original_rows_and_categories_verified=True,
        q3_full_original_field_matches=sorted(match_ids), q3_full_original_field_match_count=2,
        returned_rows=[dict(event_id=r["event_id"], pointer_identity=r["pointer_identity"],
                            issuer=r["issuer"], reported_datetime=r["reported_datetime"],
                            reported_category=r["reported_category"], subject=r["original_fields"]["SUBJECT"],
                            url=r["original_fields"]["HYPERLINK"],
                            original_fields_sha256=digest(canonical(r["original_fields"])),
                            q3_full_fields_verified=r["event_id"] in match_ids,
                            new_original_document_verified=False) for r in rows],
        declared_total_present=False, complete_announcement_population_verified=False,
        no_later_notice_proven=False, current_transaction_status_verified=False,
        current_tradability_verified=False, contractual_cash_claim_verified=False,
        source_gate_passed=False, cash_claim_source_gate_passed=False,
        historical_pit_verified=False, profit_edge_proven=False,
        valid_prospective_signal_date=None, market_prices_or_returns_read=False, orders_authorized=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    result = audit(args.root)
    path = args.root / OUT / "independent_index_audit.json"
    body = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(body)
    print(json.dumps(dict(output=str(path), sha256=digest(body), rows=9, source_gate_passed=False)))


if __name__ == "__main__":
    main()
