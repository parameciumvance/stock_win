"""Independent replay and quoted-evidence checks for the finite 19-title census.

No production parsers, network clients, quote readers or return calculations are
imported. Transaction dispositions are separately pinned human annotations;
checking their quoted source anchors does not automate their interpretation.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse
import zipfile

from lxml import html


BASE = Path("inputs/cash_merger_census_20261021")
OUT = Path("deliverables/cash_merger_census_20261021")
POLICY = Path("configs/cash_merger_census_protocol_20261021.json")
DISCOVERY_SHA256 = "b88d784df93af2f092df0a14208997e823232034b4ef636fcc9c6e9e7e4f588a"
CONTROLS_SHA256 = "6459c5976760d3698b75c27af595e044f306ef2788466814c123118cfabc6209"
# Set only after the parent has independently saved/retrieved the actual bundle
# and the finite human reading has been completed. Until then real replay fails
# before opening any source archive; synthetic pure helpers remain testable.
ORIGINALS_SHA256 = "1b051c2b4a773a4813a40198c0a8b6b76c4fdf24183a822a3abaff0eea0ad9fe"
ANNOTATION_SHA256 = "3a4cd127a9dc07a4fb98320832d6885eef151aab4e64ad777bc108c4bc3a996f"
TITLE_PATTERN = re.compile(
    r"合併|股份轉換|股份轉交換|\bmerg(?:er|e|ing)\b|\bshare\s+(?:swap|exchange)\b", re.I)
ROW_FIELDS = {"CDATE", "COMPANY_NAME", "AN_NAME", "CODE_NAME", "AN_CODE",
              "CTIME", "TYPEK", "SUBJECT", "HYPERLINK", "COMPANY_ID"}
DISPOSITIONS = {"cash_conversion_candidate", "cash_conversion_unqualified_target",
                "stock_consideration", "intragroup_no_public_cash_exit",
                "canceled_intragroup", "unclassified"}


def require(condition: object, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _identity(row: dict) -> dict:
    require(isinstance(row, dict) and set(row) == ROW_FIELDS,
            "Unexpected complete original row fields")
    require(all(isinstance(v, str) and v for v in row.values()), "Empty/nontext original field")
    require(row["TYPEK"] == "上市" and row["AN_CODE"] == "M11", "Unexpected market/category")
    require(re.fullmatch(r"\d{4,6}", row["COMPANY_ID"]), "Invalid company ID")
    require(re.fullmatch(r"\d{3}/\d{2}/\d{2}", row["CDATE"]), "Invalid ROC date")
    y, m, d = map(int, row["CDATE"].split("/"))
    day = datetime(y + 1911, m, d).date().isoformat()
    require("2026-07-01" <= day <= "2026-09-30", "Date outside fixed quarter")
    require(re.fullmatch(r"\d{2}:\d{2}:\d{2}", row["CTIME"]), "Invalid HH:MM:SS")
    datetime.strptime(row["CTIME"], "%H:%M:%S")
    url = urlparse(row["HYPERLINK"])
    require(url.scheme == "https" and url.netloc == "mopsov.twse.com.tw"
            and url.path == "/mops/web/ajax_t05sr01_1" and not url.fragment,
            "Nonofficial detail URL")
    q = parse_qs(url.query, keep_blank_values=True)
    require(set(q) == {"firstin", "stp", "step", "SEQ_NO", "SPOKE_TIME", "SPOKE_DATE", "COMPANY_ID"}
            and all(len(v) == 1 for v in q.values()), "Ambiguous detail identity")
    require(q["firstin"] == ["true"] and q["stp"] == ["1"] and q["step"] == ["1"],
            "Changed original routing")
    require(re.fullmatch(r"[1-9]\d*", q["SEQ_NO"][0]), "Invalid sequence")
    clock = q["SPOKE_TIME"][0]
    require(re.fullmatch(r"\d{1,6}", clock), "Invalid detail clock")
    require(q["COMPANY_ID"] == [row["COMPANY_ID"]]
            and q["SPOKE_DATE"] == [day.replace("-", "")]
            and clock.zfill(6) == row["CTIME"].replace(":", ""), "Original URL/time identity mismatch")
    return dict(event_id=f'M11:{row["COMPANY_ID"]}:{day}:{row["CTIME"].replace(":", "")}:{q["SEQ_NO"][0]}',
                issuer=row["COMPANY_ID"], sequence=q["SEQ_NO"][0],
                reported_datetime=day + "T" + row["CTIME"] + "+08:00",
                subject=row["SUBJECT"], source_url=row["HYPERLINK"])


def read_title_rows(quarter_body: bytes, expected_count: int = 476) -> list[dict]:
    payload = json.loads(quarter_body)
    require(isinstance(payload, dict) and set(payload) == {"data", "message", "status"}
            and payload["status"] == "success" and payload["message"] == ["回傳成功"],
            "Quarter response schema/status mismatch")
    rows = payload["data"]
    require(isinstance(rows, list) and len(rows) == expected_count and expected_count < 1000,
            "Quarter row count/cap mismatch")
    ids = [_identity(row)["event_id"] for row in rows]
    require(len(ids) == len(set(ids)), "Duplicate quarter pointer identity")
    return [row for row in rows if TITLE_PATTERN.search(row["SUBJECT"])]


def check_allocation(quarter_body: bytes, selection: dict, request_body: bytes,
                     expected_counts: tuple[int, int, int] = (19, 15, 4),
                     expected_quarter_count: int = 476) -> list[dict]:
    title_rows = read_title_rows(quarter_body, expected_quarter_count)
    title = {_identity(row)["event_id"]: row for row in title_rows}
    require(selection["source_quarter_sha256"] == digest(quarter_body), "Quarter source hash mismatch")
    rows = selection["rows"]
    require(isinstance(rows, list) and len(rows) == expected_counts[0], "Selected document count mismatch")
    selected_ids = [row["event_id"] for row in rows]
    require(len(set(selected_ids)) == len(selected_ids) and set(selected_ids) == set(title),
            "Selection drops or adds frozen title pointers")
    requests = json.loads(request_body)["requests"]
    request_map = {item["filename"]: item for item in requests}
    require(len(request_map) == len(requests) == expected_counts[1], "New request count/duplicate mismatch")
    old, new = [], []
    for row in rows:
        require(row["index_original_fields"] == title[row["event_id"]], "Complete original fields changed")
        has_old, has_new = "original_source" in row, "new_filename" in row
        require(has_old != has_new, "Exactly one source locator required")
        if has_old:
            locator = row["original_source"]
            require(isinstance(locator, dict) and set(locator) == {"archive_sha256", "member"}
                    and re.fullmatch(r"[0-9a-f]{64}", locator["archive_sha256"])
                    and re.fullmatch(r"raw/[A-Za-z0-9_.-]+", locator["member"])
                    and locator["member"] not in ("raw/.", "raw/.."), "Invalid reused source locator")
            old.append((locator["archive_sha256"], locator["member"]))
        else:
            name = row["new_filename"]
            require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", name)
                    and name not in (".", "..") and name in request_map,
                    "Invalid new source filename")
            require(request_map[name]["url"] == row["index_original_fields"]["HYPERLINK"],
                    "New request differs from selected original URL")
            new.append(name)
    require((len(rows), len(new), len(old)) == expected_counts, "Source allocation count mismatch")
    require(len(old) == len(set(old)) and len(new) == len(set(new))
            and set(new) == set(request_map), "Duplicate or incomplete source allocation")
    return rows


def read_identity(body: bytes, row: dict) -> tuple[dict, str]:
    identity = _identity(row)
    tree = html.fromstring(body, parser=html.HTMLParser(encoding="utf-8"))
    for node in tree.xpath("//script|//style"):
        node.drop_tree()
    providers = tree.xpath('//tr[td[contains(.,"本資料由")]]/td')
    require(len(providers) == 1, "Missing/ambiguous original company provider")
    require(re.search(r"\(上市公司\)\s*" + re.escape(row["COMPANY_ID"]) + r"\s*"
                      + re.escape(row["COMPANY_NAME"]) + r"\s*公司提供",
                      providers[0].text_content()), "Original company/name mismatch")
    metadata = {}
    for tr in tree.xpath("//tr"):
        cells = tr.xpath("./th|./td")
        for label, value in zip(cells, cells[1:]):
            if label.tag == "th" and value.tag == "td":
                key = label.text_content().strip()
                require(key not in metadata, "Duplicate original metadata")
                metadata[key] = value.text_content().strip()
    require(all(metadata.get(k) for k in ("序號", "發言日期", "發言時間", "主旨", "說明")),
            "Missing original identity/description")
    require(metadata["序號"] == identity["sequence"]
            and metadata["發言日期"] == row["CDATE"] and metadata["發言時間"] == row["CTIME"]
            and compact(metadata["主旨"]) == compact(row["SUBJECT"]), "Original/index metadata mismatch")
    description = metadata["說明"]
    return identity | dict(body_sha256=digest(body), description_sha256=digest(description.encode("utf-8")),
                           metadata_identity_verified=True), description


def check_annotations(annotation: dict, docs: list[dict], descriptions: dict[str, str]) -> None:
    by_id = {doc["event_id"]: doc for doc in docs}
    require(len(by_id) == len(docs) and set(by_id) == set(descriptions), "Annotation source population differs")
    rows = annotation.get("rows")
    require(isinstance(rows, list) and len(rows) == len(docs), "Missing semantic annotation rows")
    row_ids = [row.get("event_id") for row in rows]
    require(len(set(row_ids)) == len(row_ids) and set(row_ids) == set(by_id), "Annotation drops/duplicates document")
    declared_groups = {}
    for row in rows:
        doc = by_id[row["event_id"]]
        text = descriptions[row["event_id"]]
        require(row.get("body_sha256") == doc["body_sha256"], "Annotation body SHA mismatch")
        require(row.get("description_sha256") == doc["description_sha256"] == digest(text.encode("utf-8")),
                "Annotation complete description SHA mismatch")
        require(row.get("disposition") in DISPOSITIONS, "Unknown finite disposition")
        require(isinstance(row.get("deal_id"), str) and re.fullmatch(r"[A-Za-z0-9_:-]+", row["deal_id"]),
                "Missing/invalid independent deal ID")
        anchors = row.get("anchors")
        require(isinstance(anchors, list) and anchors
                and all(isinstance(q, str) and compact(q) for q in anchors), "Missing source anchor")
        for quote in anchors:
            require(compact(quote) in compact(text), "Annotated quote missing from bound original")
        declared_groups[row["event_id"]] = row["deal_id"]
    deals = annotation.get("deals")
    require(isinstance(deals, list) and deals, "Missing independent deal grouping")
    deal_ids = [deal.get("deal_id") for deal in deals]
    require(len(deal_ids) == len(set(deal_ids)), "Duplicate deal ID")
    assignments = {}
    for deal in deals:
        ids = deal.get("event_ids")
        require(isinstance(ids, list) and ids and len(ids) == len(set(ids)), "Duplicate/empty deal members")
        for event in ids:
            require(event not in assignments and event in declared_groups
                    and declared_groups[event] == deal["deal_id"], "Document assigned to wrong/multiple deals")
            assignments[event] = deal["deal_id"]
    require(assignments == declared_groups, "Deal grouping does not cover all documents")


def verify_archive_bytes(body: bytes, expected: str) -> dict[str, bytes]:
    require(digest(body) == expected, "Archive SHA mismatch")
    with zipfile.ZipFile(BytesIO(body)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) and archive.testzip() is None, "Archive duplicate/CRC failure")
        manifest = json.loads(archive.read("manifest.json"))
        require(set(names) == set(manifest) | {"manifest.json"}, "Archive manifest member mismatch")
        members = {name: archive.read(name) for name in names}
        for name, wanted in manifest.items():
            require(not Path(name).is_absolute() and ".." not in Path(name).parts
                    and digest(members[name]) == wanted, "Archive member SHA/path mismatch")
    return members


def _readback(root: Path, out: Path, batch: str, expected: str) -> tuple[dict, dict]:
    package_body = (root / out / f"{batch}_package.json").read_bytes()
    package = json.loads(package_body)
    transfer_body = (root / package["transfer_receipt"]).read_bytes()
    transfer = json.loads(transfer_body)
    require(package["sha256"] == transfer["sha256"] == expected
            and transfer["roundtrip_verified"] is True, "Archive lacks pinned successful readback")
    members = verify_archive_bytes((root / package["retrieved"]).read_bytes(), expected)
    require(package["manifest_files"] == len(members) - 1, "Package manifest count mismatch")
    return members, dict(sha256=expected, retrieved=package["retrieved"],
                         manifest_files=len(members) - 1,
                         package_sha256=digest(package_body), transfer_sha256=digest(transfer_body),
                         crc_manifest_verified=True, roundtrip_verified=True)


def _transport(members: dict, successful_names: set[str]) -> None:
    request_body = members["requests.json"]
    requests = json.loads(request_body)["requests"]
    results = json.loads(members["raw/results.json"])
    require(results["workers"] == 2 and results["config_sha256"] == digest(request_body)
            and [r["request"] for r in results["requests"]] == requests, "Transport request plan mismatch")
    by_name = {r["request"]["filename"]: r for r in results["requests"]}
    require(successful_names <= set(by_name), "Missing selected transport record")
    for name, record in by_name.items():
        require(json.loads(members[f"raw/{name}.meta.json"]) == record, "Transport metadata drift")
        for suffix, key in (("", "sha256"), (".headers", "headers_sha256")):
            if key in record:
                require(digest(members[f"raw/{name}{suffix}"]) == record[key], "Transport bytes drift")
        if name in successful_names:
            require(type(record.get("http_status")) is int and record["http_status"] == 200
                    and type(record.get("exit_code")) is int and record["exit_code"] == 0,
                    "Selected original requires HTTP200/exit0")


def load_sources(root: Path | str) -> tuple[list[dict], dict[str, str], dict]:
    """Read actual originals only after the parent supplies the verified hash."""
    require(isinstance(ORIGINALS_SHA256, str) and re.fullmatch(r"[0-9a-f]{64}", ORIGINALS_SHA256),
            "Awaiting parent-confirmed Windows archive readback")
    root = Path(root)
    protocol_body = (root / POLICY).read_bytes()
    policy = json.loads(protocol_body)
    freeze = json.loads((root / OUT / "protocol_freeze.json").read_bytes())
    require(digest(protocol_body) == freeze["protocol_sha256"], "Frozen census protocol drift")
    # Check every prior frozen input before opening source archives.
    for filename, expected in policy["prior_checkpoints"].items():
        body = (root / filename).read_bytes()
        require(digest(body) == expected, "Prior checkpoint drift")
        for name, wanted in json.loads(body)["files"].items():
            require(digest((root / name).read_bytes()) == wanted, "Prior frozen member drift")
    require((policy["expected_documents"], policy["expected_new_requests"], policy["expected_reused_documents"])
            == (19, 15, 4), "Frozen census scope differs")
    for key in ("selection_manifest", "title_census"):
        ref = policy[key]
        require(digest((root / ref["path"]).read_bytes()) == ref["sha256"], "Frozen census reference drift")
    selection_body = (root / policy["selection_manifest"]["path"]).read_bytes()
    selection = json.loads(selection_body)
    title = json.loads((root / policy["title_census"]["path"]).read_bytes())
    discovery, discovery_info = _readback(root, Path("deliverables/cash_merger_20261021"), "discovery", DISCOVERY_SHA256)
    controls, controls_info = _readback(root, Path("deliverables/cash_merger_20261021"), "controls", CONTROLS_SHA256)
    originals, originals_info = _readback(root, OUT, "originals", ORIGINALS_SHA256)
    require(originals["protocol.json"] == protocol_body, "Archived census policy differs")
    request_ref = policy["batches"]["originals"]
    request_body = (root / request_ref["path"]).read_bytes()
    require(originals["requests.json"] == request_body and digest(request_body) == request_ref["sha256"],
            "Archived census request plan differs")
    quarter = discovery["raw/m11_2026q3.json"]
    require(policy["source_quarter"]["archive_sha256"] == DISCOVERY_SHA256
            and policy["source_quarter"]["body_sha256"] == digest(quarter), "Frozen source quarter differs")
    rows = check_allocation(quarter, selection, request_body)
    require(selection["source_index_replay_sha256"] == policy["title_census"]["sha256"]
            and title["quarter_source_sha256"] == digest(quarter)
            and title["explicit_merger_title_cohort_count"] == 19
            and {r["event_id"] for r in title["explicit_merger_title_cohort"]}
                == {r["event_id"] for r in rows}, "Prior title census pointer set differs")
    names = {r["new_filename"] for r in rows if "new_filename" in r}
    reused = {r["original_source"]["member"].removeprefix("raw/") for r in rows if "original_source" in r}
    _transport(originals, names)
    _transport(controls, reused)
    _transport(discovery, {"m11_2026q3.json"})
    docs, descriptions = [], {}
    for selected in rows:
        row = selected["index_original_fields"]
        if "new_filename" in selected:
            name = selected["new_filename"]
            members, archive_sha, member = originals, ORIGINALS_SHA256, "raw/" + name
        else:
            locator = selected["original_source"]
            require(locator["archive_sha256"] == CONTROLS_SHA256, "Unexpected reused archive")
            members, archive_sha, member = controls, CONTROLS_SHA256, locator["member"]
            name = member.removeprefix("raw/")
        meta = json.loads(members[f"raw/{name}.meta.json"])
        require(meta["request"]["url"] == row["HYPERLINK"] and meta["request"]["filename"] == name,
                "Source allocation request differs from original pointer")
        doc, description = read_identity(members[member], row)
        require(doc["event_id"] == selected["event_id"], "Original document pointer differs")
        docs.append(doc | dict(source_archive_sha256=archive_sha, source_member=member))
        descriptions[doc["event_id"]] = description
    return docs, descriptions, dict(
        protocol_sha256=digest(protocol_body), selection_sha256=digest(selection_body),
        quarter_source_sha256=digest(quarter), quarter_rows=476, explicit_title_documents=19,
        new_documents=15, reused_documents=4, all_original_identities_verified=True,
        all_selected_transports_HTTP200_exit0=True,
        archives=[discovery_info, controls_info, originals_info])


def audit(root: Path | str) -> dict:
    require(isinstance(ANNOTATION_SHA256, str) and re.fullmatch(r"[0-9a-f]{64}", ANNOTATION_SHA256),
            "Awaiting completed independently pinned semantic annotations")
    root = Path(root)
    docs, descriptions, result = load_sources(root)
    path = root / OUT / "semantic_annotations.json"
    body = path.read_bytes()
    require(digest(body) == ANNOTATION_SHA256, "Semantic annotation hash drift")
    annotation = json.loads(body)
    require(annotation["source_archives"] == [DISCOVERY_SHA256, CONTROLS_SHA256, ORIGINALS_SHA256]
            and annotation["selection_sha256"] == result["selection_sha256"], "Annotation source binding differs")
    check_annotations(annotation, docs, descriptions)
    result.update(
        scope="Complete fixed explicit-title subset and human annotation anchor verification; not an all-cash-deal population or automated interpretation.",
        auditor_script_sha256=digest(Path(__file__).read_bytes()),
        semantic_annotation_sha256=ANNOTATION_SHA256,
        semantic_interpretation_is_automated=False, all_quoted_source_anchors_verified=True,
        documents=docs, deal_groups=len(annotation["deals"]),
        disposition_document_counts=dict(sorted(Counter(r["disposition"] for r in annotation["rows"]).items())),
        source_gate_passed=False, cash_claim_source_gate_passed=False,
        all_eligible_cash_mergers_known=False, historical_pit_verified=False,
        profit_edge_proven=False, valid_prospective_signal_date=None,
        market_prices_or_returns_read=False, orders_authorized=False)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, default=OUT / "independent_audit.json")
    args = parser.parse_args()
    result = audit(args.root)
    output = args.output if args.output.is_absolute() else args.root / args.output
    body = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    output.write_bytes(body)
    print(json.dumps({"output": str(output), "sha256": digest(body), "documents": 19,
                      "source_gate_passed": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
