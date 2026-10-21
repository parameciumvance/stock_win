"""Independently replay the pinned cash-merger source controls, without prices.

Only the Python standard library and lxml are used.  Semantic interpretations
live in a separately pinned human annotation; matching quoted anchors is an
evidence check, not automated legal or transaction classification.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse
import zipfile

from lxml import html


BASE = "inputs/cash_merger_20261021"
DELIVERABLES = "deliverables/cash_merger_20261021"
ARCHIVE_SHA256 = {
    "discovery": "b88d784df93af2f092df0a14208997e823232034b4ef636fcc9c6e9e7e4f588a",
    "controls": "6459c5976760d3698b75c27af595e044f306ef2788466814c123118cfabc6209",
}
ANNOTATION_SHA256 = "494460abd8babbdf837c1e192d51f2b462862ce7d116dc9c63b279a5c7feec7f"
ROW_FIELDS = {
    "CDATE", "COMPANY_NAME", "AN_NAME", "CODE_NAME", "AN_CODE", "CTIME",
    "TYPEK", "SUBJECT", "HYPERLINK", "COMPANY_ID",
}
PARTITIONS = (
    ("m11_2026q3", "2026-07-01", "2026-09-30", 476),
    ("m11_202607", "2026-07-01", "2026-07-31", 117),
    ("m11_202608", "2026-08-01", "2026-08-31", 253),
    ("m11_202609", "2026-09-01", "2026-09-30", 106),
)


def sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def require(condition: object, message: str) -> None:
    if not condition:
        raise ValueError(message)


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def roc_date(value: str) -> str:
    require(isinstance(value, str) and re.fullmatch(r"\d{3}/\d{2}/\d{2}", value),
            "Invalid ROC date")
    y, m, d = map(int, value.split("/"))
    return datetime(y + 1911, m, d).date().isoformat()


def verify_row(row: dict, start: str, end: str) -> dict:
    """Check all original fields and row/URL identity without rewriting the URL."""
    require(isinstance(row, dict) and set(row) == ROW_FIELDS,
            "Unknown index row fields")
    require(all(isinstance(v, str) and v for v in row.values()),
            "Nontext or empty index field")
    require(row["AN_CODE"] == "M11" and row["TYPEK"] == "上市",
            "Unexpected category or declared market")
    day = roc_date(row["CDATE"])
    require(start <= day <= end, "Returned date outside requested period")
    require(re.fullmatch(r"\d{2}:\d{2}:\d{2}", row["CTIME"]), "Invalid clock")
    datetime.strptime(row["CTIME"], "%H:%M:%S")
    url = urlparse(row["HYPERLINK"])
    require(url.scheme == "https" and url.netloc == "mopsov.twse.com.tw"
            and url.path == "/mops/web/ajax_t05sr01_1" and not url.fragment,
            "URL outside the official original route")
    query = parse_qs(url.query, keep_blank_values=True)
    require(set(query) == {"firstin", "stp", "step", "SEQ_NO", "SPOKE_TIME",
                           "SPOKE_DATE", "COMPANY_ID"}
            and all(len(v) == 1 for v in query.values()), "Ambiguous URL query")
    require(query["firstin"] == ["true"] and query["stp"] == ["1"]
            and query["step"] == ["1"], "Changed detail routing")
    require(re.fullmatch(r"[1-9]\d*", query["SEQ_NO"][0]), "Invalid sequence")
    # Seven archived early-morning URLs omit the leading zero.  Preserve them,
    # but compare their HHMMSS value after strictly bounded numeric padding.
    clock = query["SPOKE_TIME"][0]
    require(re.fullmatch(r"\d{1,6}", clock), "Invalid URL clock")
    require(query["COMPANY_ID"] == [row["COMPANY_ID"]]
            and query["SPOKE_DATE"] == [day.replace("-", "")]
            and clock.zfill(6) == row["CTIME"].replace(":", ""),
            "Row/URL company, date or time mismatch")
    return {
        "issuer": row["COMPANY_ID"],
        "reported_datetime": day + "T" + row["CTIME"] + "+08:00",
        "sequence": query["SEQ_NO"][0],
        "subject": row["SUBJECT"],
        "url": row["HYPERLINK"],
    }


def verify_document(body: bytes, row: dict) -> tuple[dict, str]:
    """Read independent lxml metadata and match it to its original index row."""
    identity = verify_row(row, "2026-07-01", "2026-09-30")
    tree = html.fromstring(body, parser=html.HTMLParser(encoding="utf-8"))
    for node in tree.xpath("//script|//style"):
        node.drop_tree()
    pairs = {}
    for tr in tree.xpath("//tr"):
        cells = tr.xpath("./th|./td")
        for first, second in zip(cells, cells[1:]):
            if first.tag == "th" and second.tag == "td":
                key = first.text_content().strip()
                require(key not in pairs, "Duplicate metadata label")
                pairs[key] = second.text_content().strip()
    for key in ("序號", "發言日期", "發言時間", "主旨", "說明"):
        require(pairs.get(key), f"Missing document metadata {key}")
    providers = tree.xpath('//tr[td[contains(.,"本資料由")]]/td')
    require(len(providers) == 1, "Absent or ambiguous issuer provider")
    pattern = (r"\(上市公司\)\s*" + re.escape(row["COMPANY_ID"])
               + r"\s*" + re.escape(row["COMPANY_NAME"]) + r"\s*公司提供")
    require(re.search(pattern, providers[0].text_content()), "Company mismatch")
    require(pairs["序號"] == identity["sequence"]
            and pairs["發言日期"] == row["CDATE"]
            and pairs["發言時間"] == row["CTIME"]
            and compact(pairs["主旨"]) == compact(row["SUBJECT"]),
            "Document/index identity mismatch")
    description = pairs["說明"]
    return identity | {
        "subject": pairs["主旨"],
        "sha256": sha256(body),
        "description_sha256": sha256(description.encode("utf-8")),
        "declared_issuer_market": "上市公司",
        "identity_verified": True,
    }, description


def full_field_multisets_equal(quarter: list[dict], months: list[list[dict]]) -> bool:
    """Compare every original field, preserving whitespace and multiplicity."""
    def canonical(row: dict) -> str:
        return json.dumps(row, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))
    return Counter(map(canonical, quarter)) == Counter(
        canonical(row) for month in months for row in month)


def verify_annotation_evidence(annotation: dict, documents: list[dict],
                               descriptions: dict[str, str]) -> None:
    """Verify source bindings and quoted anchors, not the interpretation text."""
    require(len({d["filename"] for d in documents}) == len(documents),
            "Duplicate document filenames")
    by_name = {d["filename"]: d for d in documents}
    require(set(descriptions) == set(by_name), "Description/document mismatch")
    covered = set()
    notes = annotation.get("semantic_reading")
    require(isinstance(notes, list) and notes, "Missing semantic annotation notes")
    for note in notes:
        numbers = note.get("document_numbers")
        require(isinstance(numbers, list) and numbers
                and all(type(i) is int and 1 <= i <= len(documents) for i in numbers)
                and len(set(numbers)) == len(numbers), "Invalid annotated document numbers")
        expected = {documents[i - 1]["filename"] for i in numbers}
        evidence = note.get("evidence")
        require(isinstance(evidence, list) and evidence, "Missing annotation evidence")
        names = [e.get("filename") for e in evidence]
        require(len(names) == len(set(names)) and set(names) == expected,
                "Annotation evidence bound to wrong documents")
        for item in evidence:
            name = item["filename"]
            doc = by_name[name]
            text = descriptions[name]
            require(item.get("sha256") == doc["sha256"], "Annotation source SHA mismatch")
            actual = sha256(text.encode("utf-8"))
            require(item.get("description_sha256") == doc["description_sha256"] == actual,
                    "Annotation description SHA mismatch")
            quotes = item.get("exact_excerpts")
            require(isinstance(quotes, list) and quotes
                    and all(isinstance(q, str) and compact(q) for q in quotes),
                    "Missing annotation anchor strings")
            for quote in quotes:
                require(compact(quote) in compact(text), f"Missing source anchor in {name}")
        covered.update(expected)
    require(covered == set(by_name), "Document lacks semantic annotation")


def read_archive(root: Path, stem: str) -> tuple[dict[str, bytes], dict]:
    path = root / BASE / f"{stem}.retrieved.zip"
    pinned = ARCHIVE_SHA256[stem]
    require(sha256(path.read_bytes()) == pinned, f"{stem} archive hash mismatch")
    with zipfile.ZipFile(path) as archive:
        require(archive.testzip() is None, f"{stem} CRC failure")
        names = archive.namelist()
        require(len(names) == len(set(names)), f"{stem} duplicate ZIP member")
        manifest = json.loads(archive.read("manifest.json"))
        require(set(names) == set(manifest) | {"manifest.json"},
                f"{stem} manifest member mismatch")
        data = {name: archive.read(name) for name in names}
        for name, digest in manifest.items():
            require(sha256(data[name]) == digest, f"{stem}/{name} digest mismatch")
    receipt_path = root / DELIVERABLES / f"source_receipt_{stem}.json"
    receipt = json.loads(receipt_path.read_bytes())
    require(receipt["archive_sha256"] == pinned
            and receipt["roundtrip_verified"] is True
            and receipt["crc_manifest_verified"] is True
            and receipt["manifest_files"] == len(manifest), f"{stem} receipt mismatch")
    return data, {
        "path": str(path.relative_to(root)), "sha256": pinned, "crc_passed": True,
        "manifest_members_verified": len(manifest),
        "manifest_sha256": sha256(data["manifest.json"]),
        "receipt_sha256": sha256(receipt_path.read_bytes()),
    }


def audit(root: Path | str) -> dict:
    root = Path(root)
    discovery, discovery_info = read_archive(root, "discovery")
    controls, controls_info = read_archive(root, "controls")
    require(controls["protocol.json"] == discovery["protocol.json"],
            "Source archives disagree on protocol bytes")
    require(controls["protocol.json"] == (
        root / "configs/cash_merger_protocol_20261021.json").read_bytes(),
        "Live frozen protocol drift")
    indexes, infos = {}, {}
    legacy_groups = defaultdict(list)
    for name, start, end, count in PARTITIONS:
        body = discovery[f"raw/{name}.json"]
        meta = json.loads(discovery[f"raw/{name}.json.meta.json"])
        payload = json.loads(body)
        require(meta["http_status"] == 200 and meta["exit_code"] == 0
                and meta["sha256"] == sha256(body), f"{name} receipt mismatch")
        require(set(payload) == {"data", "message", "status"}
                and payload["status"] == "success"
                and payload["message"] == ["回傳成功"], f"{name} response schema")
        rows = payload["data"]
        require(isinstance(rows, list) and len(rows) == count and count < 1000,
                f"{name} frozen row count mismatch")
        request = parse_qs(meta["request"]["data"], keep_blank_values=True)
        require(request["PRO_ITEM"] == ["M11"] and request["TYPEK"] == ["sii"]
                and request["CO_MARKET"] == [""]
                and roc_date(request["SDATE"][0]) == start
                and roc_date(request["EDATE"][0]) == end,
                f"{name} request period/category/market mismatch")
        identities = []
        for number, row in enumerate(rows, 1):
            identity = verify_row(row, start, end)
            key = (identity["issuer"], identity["reported_datetime"], identity["sequence"])
            identities.append(key)
            if name == "m11_2026q3":
                group = (identity["issuer"], identity["reported_datetime"][:10],
                         identity["sequence"])
                legacy_groups[group].append({"row": number, "time": row["CTIME"],
                                             "subject": row["SUBJECT"]})
        require(len(set(identities)) == len(identities), f"{name} duplicate full identity")
        indexes[name] = rows
        infos[name] = {"sha256": sha256(body), "row_count": count,
                       "url_time_company_date_checks": count,
                       "all_declared_market": "上市", "below_observed_1000_row_cap": True}
    require(full_field_multisets_equal(indexes["m11_2026q3"],
            [indexes[name] for name, *_ in PARTITIONS[1:]]),
            "Quarter/month full original field multiset mismatch")
    selection_path = root / DELIVERABLES / "controls_selection.json"
    selection = json.loads(selection_path.read_bytes())
    require(selection["source_archive_sha256"] == discovery_info["sha256"]
            and selection["source_body_sha256"] == infos["m11_2026q3"]["sha256"],
            "Selection source drift")
    requests = json.loads(controls["requests.json"])["requests"]
    require(len(requests) == len(selection["rows"]) == 6, "Wrong number of controls")
    documents, descriptions = [], {}
    for request, selected in zip(requests, selection["rows"]):
        row = selected["original_fields"]
        number = selected["source_row_number"]
        require(type(number) is int and 1 <= number <= 476
                and indexes["m11_2026q3"][number - 1] == row,
                "Selection differs from original index row")
        require(request["url"] == row["HYPERLINK"], "Request differs from selected URL")
        name = request["filename"]
        body = controls["raw/" + name]
        meta = json.loads(controls["raw/" + name + ".meta.json"])
        require(meta["http_status"] == 200 and meta["exit_code"] == 0
                and meta["sha256"] == sha256(body) and meta["request"] == request,
                "Control body/receipt/request mismatch")
        identity, description = verify_document(body, row)
        documents.append({"filename": name, "source_row": number,
                          "semantic_role": selected["role"], **identity})
        descriptions[name] = description
    annotation_path = root / DELIVERABLES / "semantic_annotations.json"
    annotation_body = annotation_path.read_bytes()
    require(sha256(annotation_body) == ANNOTATION_SHA256, "Human annotation hash mismatch")
    annotation = json.loads(annotation_body)
    require(annotation["source_archives"] == {
        info["path"]: info["sha256"] for info in (discovery_info, controls_info)},
        "Human annotation source archives mismatch")
    verify_annotation_evidence(annotation, documents, descriptions)
    moj = json.loads(discovery["raw/merger_act.html.meta.json"])
    tax = json.loads(discovery["raw/cash_merger_tax_ruling.html.meta.json"])
    require(moj["http_status"] == 0 and moj["exit_code"] == 7
            and "raw/merger_act.html" not in discovery, "MOJ failure evidence changed")
    legal_anchor = annotation["legal_anchor"]
    tax_body = discovery[legal_anchor["filename"]]
    require(legal_anchor["archive"] == "discovery"
            and tax["http_status"] == 200 and tax["exit_code"] == 0
            and tax["sha256"] == legal_anchor["sha256"] == sha256(tax_body),
            "Tax source body mismatch")
    tax_tree = html.fromstring(tax_body, parser=html.HTMLParser(encoding="utf-8"))
    for quote in legal_anchor["exact_excerpts"]:
        require(compact(quote) in compact(tax_tree.text_content()), "Missing tax source anchor")
    result = {
        "scope": "Independent archived-source identity replay and human annotation anchor verification only; no production parser helpers, prices, returns, network or trades.",
        "auditor_script_path": "cash_merger_independent.py",
        "auditor_script_sha256": sha256(Path(__file__).read_bytes()),
        "archives": [discovery_info, controls_info],
        "protocol_sha256": sha256(controls["protocol.json"]),
        "selection_sha256": sha256(selection_path.read_bytes()),
        "semantic_annotation_path": str(annotation_path.relative_to(root)),
        "semantic_annotation_sha256": ANNOTATION_SHA256,
        "semantic_interpretation_is_automated": False,
        "all_quoted_source_anchors_verified": True,
        "index_partitions": infos,
        "quarter_month_full_original_field_multisets_equal": True,
        "quarter_total_records": 476, "month_total_records": 476,
        "full_identities_unique": True,
        "legacy_company_date_sequence_collision_groups": [
            {"issuer": k[0], "date": k[1], "sequence": k[2], "members": v}
            for k, v in legacy_groups.items() if len(v) > 1],
        "control_documents": documents,
    }
    for key in ("semantic_reading", "index_limitations", "legal_sources",
                "candidate_conclusion", "resolvable_without_user", "unresolved_claim_inputs"):
        result[key] = annotation[key]
    result.update(source_gate_passed=False, historical_pit_verified=False,
                  complete_population_verified=False, profit_edge_proven=False,
                  valid_prospective_signal_date=None, trade_authorized=False)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path,
                        default=Path(DELIVERABLES) / "independent_control_audit.json")
    args = parser.parse_args()
    result = audit(args.root)
    output = args.output if args.output.is_absolute() else args.root / args.output
    body = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    # Write only after every archive, identity and evidence check succeeds.
    output.write_bytes(body)
    print(json.dumps({"output": str(output), "sha256": sha256(body),
                      "control_documents": len(result["control_documents"]),
                      "quarter_records": result["quarter_total_records"],
                      "source_gate_passed": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
