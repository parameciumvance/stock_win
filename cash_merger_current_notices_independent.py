"""Independent, finite reading of three saved meeting/delisting notices."""
import argparse
import json
from pathlib import Path
import re

from lxml import html

from cash_merger_census_independent import _readback, _transport
from cash_merger_current_index_independent import _row, digest, parse_saved_index, require, strict_json


OUT = Path("deliverables/cash_merger_current_followthrough_20261022")
POLICY = Path("configs/cash_merger_current_followthrough_protocol_20261022.json")
ARCHIVE_SHA256 = "8ffff95f73a323b057715752baf0a26621ad8208ec55e5e0ff5b5ab17390b35e"
INDEX_SHA256 = "8b5174da2086dbb7de6f02b884f0c858e958abbfc5581f7c18d0ecf7b6c270ea"
ANNOTATION_SHA256 = "1963a3418b6aad25ee3444f4a655b76eed4d657db1a3fd9e1a4057dd8910317f"


def compact(text):
    return re.sub(r"\s+", "", text)


def read_notice(body, original):
    identity = _row(original, "6674", "2026-09-18", "2026-10-21")
    tree = html.fromstring(body, parser=html.HTMLParser(encoding="utf-8"))
    pointers = [dict(tag=node.tag, attribute=name, value=value)
                for node in tree.iter() for name, value in node.attrib.items() if name in ("href", "src")]
    providers = tree.xpath('//tr[td[contains(.,"本資料由")]]/td')
    require(len(providers) == 1 and re.search(
        r"\(上市公司\)\s*6674\s*" + re.escape(original["COMPANY_NAME"]) + r"\s*公司提供",
        providers[0].text_content()), "Notice provider mismatch")
    metadata = {}
    for tr in tree.xpath("//tr"):
        cells = tr.xpath("./th|./td")
        for label, value in zip(cells, cells[1:]):
            if label.tag == "th" and value.tag == "td":
                key = label.text_content().strip()
                require(key not in metadata, "Duplicate notice metadata")
                metadata[key] = value.text_content().strip()
    require(all(metadata.get(k) for k in ("序號", "發言日期", "發言時間", "主旨", "說明")),
            "Missing notice identity/description")
    require(metadata["序號"] == identity["pointer_identity"].split(":")[-1]
            and metadata["發言日期"] == original["CDATE"] and metadata["發言時間"] == original["CTIME"]
            and compact(metadata["主旨"]) == compact(original["SUBJECT"]), "Notice/index identity mismatch")
    description = metadata["說明"]
    return {k: v for k, v in identity.items() if k != "original_fields"} | dict(
        body_sha256=digest(body), description_sha256=digest(description.encode("utf-8")),
        pointers=pointers, metadata_identity_verified=True), description


def compare_meetings(original, amendment):
    def fields(description):
        matches = list(re.finditer(r"(?m)^([0-9]+)\.", description))
        result = {}
        for number, match in enumerate(matches):
            key = int(match[1])
            require(key not in result, "Duplicate meeting numbered field")
            result[key] = description[match.end():matches[number + 1].start() if number + 1 < len(matches) else len(description)].strip()
        require(set(result) == set(range(1, 11)), "Meeting form lacks its complete ten fields")
        return result
    old, new = fields(original), fields(amendment)
    changed = [n for n in old if old[n] != new[n]]
    return dict(changed_numbered_fields=changed, venue_only_change=changed == [3],
                shareholder_meeting_bookclosure_is_cash_record_date=False)


def verify_annotation(annotation, docs, descriptions):
    by_id = {doc["event_id"]: doc for doc in docs}
    rows = annotation["rows"]
    require(len(rows) == len(by_id) == len(docs) and len({r["event_id"] for r in rows}) == len(rows)
            and {r["event_id"] for r in rows} == set(by_id) == set(descriptions), "Notice annotation population differs")
    for row in rows:
        doc, text = by_id[row["event_id"]], descriptions[row["event_id"]]
        require(row["body_sha256"] == doc["body_sha256"] and row["description_sha256"]
                == doc["description_sha256"] == digest(text.encode("utf-8")), "Notice annotation source SHA mismatch")
        require(row.get("anchors") and all(isinstance(q, str) and compact(q) and compact(q) in compact(text)
                for q in row["anchors"]), "Notice annotation anchor mismatch")


def load_sources(root):
    root = Path(root)
    policy_body = (root / POLICY).read_bytes()
    policy = strict_json(policy_body)
    require(digest(policy_body) == strict_json((root / OUT / "protocol_freeze.json").read_bytes())["protocol_sha256"],
            "Frozen followthrough protocol drift")
    for filename, expected in policy["prior_checkpoints"].items():
        body = (root / filename).read_bytes()
        require(digest(body) == expected, "Prior checkpoint drift")
        for name, wanted in strict_json(body)["files"].items():
            require(digest((root / name).read_bytes()) == wanted, "Prior frozen member drift")
    saved, archive = _readback(root, OUT, "notices", ARCHIVE_SHA256)
    require(saved["protocol.json"] == policy_body and archive["manifest_files"] == 12,
            "Notice archive policy/count mismatch")
    selection_ref = policy["selection_manifest"]
    selection_body = (root / selection_ref["path"]).read_bytes()
    require(digest(selection_body) == selection_ref["sha256"], "Notice selection drift")
    selection = strict_json(selection_body)
    request_ref = policy["batches"]["notices"]
    request_body = (root / request_ref["path"]).read_bytes()
    require(saved["requests.json"] == request_body and digest(request_body) == request_ref["sha256"],
            "Archived notice request configuration differs")
    requests = {r["filename"]: r for r in strict_json(request_body)["requests"]}
    require(len(requests) == len(selection["rows"]) == 3
            and set(requests) == {r["new_filename"] for r in selection["rows"]}, "Notice request population differs")
    _transport(saved, set(requests))
    index, index_archive = _readback(root, Path("deliverables/cash_merger_current_20261021"), "index", INDEX_SHA256)
    index_body = index["raw/target_6674_m00.json"]
    require(selection["source_archive_sha256"] == INDEX_SHA256
            and selection["source_index_sha256"] == digest(index_body), "Parent index binding differs")
    by_id = {r["event_id"]: r["original_fields"] for r in parse_saved_index(index_body, "6674")["rows"]}
    docs, descriptions = [], {}
    for selected in selection["rows"]:
        identity, name, original = selected["event_id"], selected["new_filename"], selected["index_original_fields"]
        require(identity in by_id and original == by_id[identity]
                and requests[name]["url"] == original["HYPERLINK"], "Selected original fields/request URL differ")
        doc, description = read_notice(saved["raw/" + name], original)
        require(doc["event_id"] == identity and identity not in descriptions, "Duplicate/wrong notice identity")
        docs.append(doc | dict(filename=name, source_member="raw/" + name))
        descriptions[identity] = description
    return docs, descriptions, dict(protocol_sha256=digest(policy_body), selection_sha256=digest(selection_body),
                                   request_config_sha256=digest(request_body), archive=archive, index_archive=index_archive)


def audit(root):
    require(isinstance(ANNOTATION_SHA256, str), "Awaiting pinned human notice reading")
    docs, descriptions, result = load_sources(root)
    body = (Path(root) / OUT / "notice_semantic_annotations.json").read_bytes()
    require(digest(body) == ANNOTATION_SHA256, "Notice semantic annotation drift")
    annotation = strict_json(body)
    require(annotation["source_archive_sha256"] == ARCHIVE_SHA256
            and annotation["source_index_archive_sha256"] == INDEX_SHA256
            and annotation["selection_sha256"] == result["selection_sha256"], "Notice annotation source differs")
    verify_annotation(annotation, docs, descriptions)
    old = descriptions["M17:6674:2026-09-18:202533:4"]
    amendment = descriptions["M17:6674:2026-09-21:155000:1"]
    comparison = compare_meetings(old, amendment)
    require(comparison["venue_only_change"], "Saved meeting amendment changes more than venue")
    expected_pointers = [dict(tag="link", attribute="href", value="css/css2.css"),
                         dict(tag="script", attribute="src", value="js/mops2.js")]
    require(all(d["pointers"] == expected_pointers for d in docs), "Saved notice pointers differ from the finite reading")
    result.update(
        scope="Independent three-original identity, meeting-field difference and human source-anchor verification; no automatic legal interpretation.",
        auditor_script_sha256=digest(Path(__file__).read_bytes()), semantic_annotation_sha256=ANNOTATION_SHA256,
        semantic_interpretation_is_automated=False, all_source_anchors_verified=True,
        document_count=3, all_original_identities_verified=True, documents=docs,
        meeting_comparison=comparison, only_saved_css_js_pointers=True,
        saved_pdf_or_issuer_IR_pointer_count=0,
        no_attachment_pointer_does_not_prove_contract_unobtainable=True,
        source_gate_passed=False, cash_claim_source_gate_passed=False,
        current_tradability_verified=False, cash_entitlement_record_date_verified=False,
        shareholder_approval_observed=False, final_delisting_date_verified=False,
        historical_pit_verified=False, profit_edge_proven=False,
        valid_prospective_signal_date=None, market_prices_or_returns_read=False, orders_authorized=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    result = audit(args.root)
    path = args.root / OUT / "independent_notices_audit.json"
    body = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(body)
    print(json.dumps(dict(output=str(path), sha256=digest(body), documents=3, source_gate_passed=False)))


if __name__ == "__main__":
    main()
