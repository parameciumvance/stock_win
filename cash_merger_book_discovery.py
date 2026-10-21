"""Verify three pinned electronic-book discovery pages; never execute forms/JS."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urljoin

from lxml import html

from cash_merger_census_independent import _readback, _transport
from cash_merger_current_index_independent import digest, require, strict_json


OUT = Path("deliverables/cash_merger_current_followthrough_20261022")
POLICY = Path("configs/cash_merger_current_followthrough_protocol_20261022.json")
SOURCES = (
    ("ebook_entry", "522cc8753d9ef9c0a8444f6723852ffad4d69a2266ebb553421b2bf3025f8ced", "official_ebook_entry.html"),
    ("ebook_routes", "23421eaf58b9811fc06a16506886864aa2f7ed1dd1b2ace5915d54e60135bdc0", "official_ebook_routes.html"),
    ("ebook_form", "22c703e01eba0fc056718079a2838ca518ab8b90ac5354536b6c1f22667c7720", "official_meeting_book_form.html"),
)
ENTRY_FIELDS = [("step", "1"), ("run", ""), ("firstin", "Y"), ("keyword", "電子書")]
FINAL_FIELDS = [("step", "1"), ("firstin", "ture"), ("off", "1"), ("TYPEK", "all"),
                ("keyword4", ""), ("code1", ""), ("TYPEK2", ""), ("checkbtn", ""),
                ("queryName", "co_id"), ("inpuType", "co_id"), ("co_id", ""), ("year", "")]
LEGACY_SHA256 = "a010fff003385d806552dc27b7a934b6dcf3b524839fb7580a8c6fe8ee3ef95d"
LEGACY_BODY_SHA256 = "3181c6fc0865e890095c14075ab9a4a0d76ac0a605c94d0440d69bdf7eef2891"


def _tree(body):
    return html.fromstring(body, parser=html.HTMLParser(encoding="utf-8"))


def _form(tree, name):
    forms = tree.xpath('//form[@name=$name]', name=name)
    require(len(forms) == 1, "Missing/ambiguous named form")
    return forms[0]


def _inputs(form):
    require(not form.xpath('.//select|.//textarea'), "Unreviewed non-input form control")
    fields = [dict(name=node.get("name"), value=node.get("value", ""),
                   value_attribute_present="value" in node.attrib,
                   type=node.get("type", "text").lower()) for node in form.xpath('.//input[@name]')]
    require(len({f["name"] for f in fields}) == len(fields), "Duplicate form field name")
    return fields


def inspect_lineage(entry_body, routes_body, form_body):
    entry, routes, final = map(_tree, (entry_body, routes_body, form_body))
    fm1 = _form(entry, "fm1")
    entry_fields = _inputs(fm1)
    require(fm1.get("action") == "/mops/web/t146sb08" and fm1.get("method", "get").lower() == "post",
            "Electronic-book relay action/method differs")
    require([(f["name"], f["value"]) for f in entry_fields] == ENTRY_FIELDS,
            "Electronic-book relay fields/defaults differ")
    entry_script = "\n".join(entry.xpath('//script/text()'))
    require(re.search(r"document\s*\.\s*fm1\s*\.\s*submit\s*\(\s*\)\s*;", entry_script),
            "Relay submit declaration missing")
    anchors = [a for a in routes.xpath('//a[@href]')
               if re.sub(r"\s+", "", a.text_content()) == "年報及股東會相關資料(含存託憑證資料)"]
    require(len(anchors) == 1 and anchors[0].get("href") == "t57sb01_q5", "Meeting-book route anchor differs")
    resolved = urljoin("https://mopsov.twse.com.tw/mops/web/t146sb08", anchors[0].get("href"))
    require(resolved == "https://mopsov.twse.com.tw/mops/web/t57sb01_q5", "Meeting-book route resolution differs")
    form = _form(final, "form1")
    require(form.get("action") == "/mops/web/ajax_t57sb01_q5" and form.get("method", "get").lower() == "post",
            "Final meeting-book form action/method differs")
    fields = _inputs(form)
    require([(f["name"], f["value"]) for f in fields] == FINAL_FIELDS,
            "Final form complete field names/defaults differ")
    expected_types = ["hidden"] * 10 + ["text", "text"]
    require([f["type"] for f in fields] == expected_types, "Final form input types differ")
    # Read the declared doAction branch; do not evaluate browser JavaScript.
    scripts = "\n".join(final.xpath('//script/text()'))
    scripts = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", scripts)
    do_action = re.search(r"function\s+doAction\s*\(\s*\)\s*\{(.*?)\n\s*\}\s*(?=function)", scripts, re.S)
    require(do_action, "Declared doAction function missing")
    compact = re.sub(r"\s+", "", do_action[1])
    firstin = "if(document.form1.firstin!=null&&document.form1.firstin!=undefined&&document.form1.firstin.value!=''){document.form1.firstin.value='1';}"
    require(firstin in compact, "Declared firstin-to1 branch missing/changed")
    require("varname=document.fh.funcName.value;document.form1.action='/mops/web/ajax_'+name;" in compact,
            "Declared form action dispatch differs")
    fh = _form(final, "fh")
    names = fh.xpath('.//input[@name="funcName"]/@value')
    require(names == ["t57sb01_q5"], "Declared dispatch function name differs")
    return dict(
        relay_form=dict(name="fm1", action=fm1.get("action"), method="POST", fields=entry_fields,
                        declared_submit="document.fm1.submit();", javascript_executed=False),
        route_anchor=dict(text=anchors[0].text_content().strip(), literal_href=anchors[0].get("href"), resolved_url=resolved),
        meeting_book_form=dict(name="form1", action=form.get("action"), method="POST", fields=fields,
                               declared_firstin_default="ture", declared_firstin_after_doAction="1",
                               declared_dispatch_function="t57sb01_q5", javascript_executed=False),
        company_year_query_performed=False, document_link_selected=False,
        contract_acquired=False, contractual_cash_claim_verified=False)


def audit(root):
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
    pages, records = {}, []
    for stem, expected, filename in SOURCES:
        saved, archive = _readback(root, OUT, stem, expected)
        require(archive["manifest_files"] == 7 and saved["protocol.json"] == policy_body, "Discovery package scope differs")
        freeze_path = root / OUT / f"{stem}_freeze.json"
        freeze_body = freeze_path.read_bytes()
        require(saved["batch_freeze.json"] == freeze_body, "Archived discovery freeze differs")
        freeze = strict_json(freeze_body)
        request_body = (root / freeze["path"]).read_bytes()
        require(digest(request_body) == freeze["sha256"] and saved["requests.json"] == request_body
                and freeze["protocol_sha256"] == digest(policy_body) and freeze["requests"] == 1,
                "Discovery request/freeze differs")
        requests = strict_json(request_body)["requests"]
        require(len(requests) == 1 and requests[0]["filename"] == filename, "Discovery request population differs")
        _transport(saved, {filename})
        body = saved["raw/" + filename]
        pages[stem] = dict(body=body, body_sha256=digest(body), request=requests[0], freeze=freeze)
        record = strict_json(saved["raw/" + filename + ".meta.json"])
        records.append(dict(batch=stem, member="raw/" + filename, body_sha256=digest(body), archive=archive,
                            request=requests[0], http_status=record["http_status"], exit_code=record["exit_code"],
                            request_started_at=record["request_started_at"], observed_at=record["observed_at"],
                            batch_freeze_sha256=digest(freeze_body)))
    entry, routes, final = [pages[name] for name, *_ in SOURCES]
    evidence = entry["freeze"]["evidence"]
    require(len(evidence) == 1 and evidence[0]["archive_sha256"] == LEGACY_SHA256
            and evidence[0]["member"] == "raw/legacy_basic.html" and evidence[0]["body_sha256"] == LEGACY_BODY_SHA256
            and evidence[0]["literal_action"] == "document.fh.action='/mops/web/autoAction';document.fh.submit();",
            "Saved legacy entry lineage binding differs")
    require(entry["request"]["url"] == "https://mopsov.twse.com.tw/mops/web/autoAction"
            and entry["request"].get("method") == "POST"
            and parse_qsl(entry["request"]["data"], keep_blank_values=True) == [
                ("firstin", "1"), ("TYPEK", "all"), ("step", "1"), ("co_id", ""),
                ("funcName", "t35sb01_q1"), ("searchtype", ""), ("inpuType", "keyword"),
                ("auto-more", ""), ("keycon", ""), ("keyword", "電子書")], "Entry request differs")
    require(routes["request"]["url"] == "https://mopsov.twse.com.tw/mops/web/t146sb08"
            and routes["request"].get("method") == "POST"
            and parse_qsl(routes["request"]["data"], keep_blank_values=True) == ENTRY_FIELDS, "Relay request differs")
    require(final["request"] == dict(filename="official_meeting_book_form.html",
                url="https://mopsov.twse.com.tw/mops/web/t57sb01_q5"), "Final form GET differs")
    for child, parent, expected_parent, member in ((routes, entry, SOURCES[0][1], "raw/official_ebook_entry.html"),
                                                   (final, routes, SOURCES[1][1], "raw/official_ebook_routes.html")):
        refs = child["freeze"]["evidence"]
        require(len(refs) == 1 and refs[0]["archive_sha256"] == expected_parent
                and refs[0]["member"] == member and refs[0]["body_sha256"] == parent["body_sha256"],
                "Parent/child discovery source lineage differs")
    route_evidence = routes["freeze"]["evidence"][0]
    require(route_evidence["form_name"] == "fm1" and route_evidence["form_action"] == "/mops/web/t146sb08"
            and route_evidence["all_form_fields"] == [list(pair) for pair in ENTRY_FIELDS], "Frozen relay form evidence differs")
    final_evidence = final["freeze"]["evidence"][0]
    require(final_evidence["literal_href"] == "t57sb01_q5"
            and final_evidence["anchor_text"] == "年報及股東會相關資料(含存託憑證資料)", "Frozen anchor evidence differs")
    for offset, page in enumerate((entry, routes, final)):
        freeze = page["freeze"]
        require((freeze["spent_before"], freeze["combined_spent_after_if_attempted"],
                 freeze["combined_ceiling"], freeze["unspent_after"]) == (5 + offset, 6 + offset, 8, 2 - offset),
                "Completed discovery request ledger differs")
    lineage = inspect_lineage(entry["body"], routes["body"], final["body"])
    return dict(
        scope="Saved UI route/form discovery evidence only; no new company/year query, attachment or contract qualification.",
        auditor_script_sha256=digest(Path(__file__).read_bytes()), protocol_sha256=digest(policy_body),
        discovery_pages=records, legacy_entry_evidence_binding_verified=True,
        legacy_parent_archive_reverified_by_this_stage=False,
        legacy_parent_verification_scope="Existing frozen source proof retained; this stage checks its exact archive/member/body binding.",
        **lineage, completed_current_and_followthrough_requests=8,
        old_combined_request_ceiling=8, old_request_budget_remaining=0,
        further_company_year_query_requires_separately_frozen_protocol_and_budget=True,
        source_gate_passed=False, cash_claim_source_gate_passed=False,
        historical_pit_verified=False, profit_edge_proven=False,
        valid_prospective_signal_date=None, market_prices_or_returns_read=False, orders_authorized=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    result = audit(args.root)
    path = args.root / OUT / "ebook_discovery.json"
    body = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(body)
    print(json.dumps(dict(output=str(path), sha256=digest(body), source_gate_passed=False)))


if __name__ == "__main__":
    main()
