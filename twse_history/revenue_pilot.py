"""Audit an issuer/SEC revenue pilot without inventing first-publication times.

Run with an explicit source config and raw cache. Network downloads are opt-in;
cached bytes are verified against metadata before parsing. Outputs are source
evidence, not a strict release ledger or model input.
"""
from __future__ import annotations

import argparse
import calendar
from datetime import date, datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.request
from zoneinfo import ZoneInfo


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def visible_text(html):
    parser = VisibleText()
    parser.feed(html)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def load_source(root, name, url, fetch=False):
    if not re.fullmatch(r"[a-zA-Z0-9_]+", name):
        raise ValueError("Unsafe cache name")
    path = root / (name + (".json" if url.endswith(".json") else ".html"))
    meta_path = root / (name + ".meta.json")
    if not path.exists() or not meta_path.exists():
        if not fetch:
            raise FileNotFoundError(f"Missing source cache: {name}")
        request = urllib.request.Request(url, headers={
            "User-Agent": "stock-win-research/1.0 (historical source validation)"})
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            meta = {"source_url": url, "final_url": response.url,
                    "http_status": response.status,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        root.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    raw = path.read_bytes()
    meta = json.loads(meta_path.read_text())
    if meta["source_url"] != url or meta["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError(f"Source identity/checksum mismatch: {name}")
    if meta.get("final_url", url) != url or meta.get("http_status", 200) != 200:
        raise ValueError(f"Redirected/error source cannot be parsed: {name}")
    return raw.decode("utf-8"), meta


def parse_issuer_date(html, revenue_month):
    text = visible_text(html)
    year, month = map(int, revenue_month.split("-"))
    title = f"TSMC {calendar.month_name[month]} {year} Revenue Report"
    if title not in text:
        raise ValueError("Issuer report month/title mismatch")
    match = re.search(r"Issued on:\s*(\d{4}/\d{2}/\d{2})", text)
    if not match:
        raise ValueError("Missing visible issue date")
    issue_date = date.fromisoformat(match[1].replace("/", "-"))
    if issue_date <= date(year, month, calendar.monthrange(year, month)[1]):
        raise ValueError("Release does not follow revenue month")
    # datePublished/dateModified/datetime attributes are not publication proof.
    return issue_date


def parse_sec_revenue(html, revenue_month):
    text = visible_text(html)
    year, month = map(int, revenue_month.split("-"))
    title = f"TSMC {calendar.month_name[month]} {year} Revenue Report"
    if title not in text or "TWSE: 2330" not in text:
        raise ValueError("SEC issuer/month identity mismatch")
    unit = re.search(r"1\.\s*Revenue\s*\(in NT\$ thousands\)", text)
    if not unit:
        raise ValueError("Missing exact revenue table/unit")
    table = text[unit.end():]
    match = re.search(r"Period Items\s+" + str(year) + r"\s+" + str(year - 1)
                      + r"\s+" + calendar.month_abbr[month]
                      + r"\.\s+Net Revenue\s+([\d,]+)\s+([\d,]+)", table)
    if not match:
        raise ValueError("Missing monthly exact revenue row")
    current, previous = (int(x.replace(",", "")) for x in match.groups())
    if current < 0 or previous <= 0:
        raise ValueError("Invalid revenue values")
    yoy_match = re.search(r"an (increase|decrease) of ([\d.]+) percent from "
                          + calendar.month_name[month] + " " + str(year - 1), text)
    if not yoy_match:
        raise ValueError("Missing reported monthly YoY")
    yoy = float(yoy_match[2]) * (1 if yoy_match[1] == "increase" else -1)
    computed = (current / previous - 1) * 100
    if abs(computed - yoy) > 0.051:
        raise ValueError("Reported YoY inconsistent with exact revenue table")
    return current, previous, yoy


def reconcile_acceptance(index_html, submissions, accession, document):
    text = visible_text(index_html)
    if accession not in text or document not in text or "Form 6-K" not in text:
        raise ValueError("Wrong SEC accession/document/form")
    match = re.search(r"Accepted\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", text)
    if not match:
        raise ValueError("Missing SEC acceptance clock")
    recent = submissions["filings"]["recent"]
    positions = [i for i, value in enumerate(recent["accessionNumber"]) if value == accession]
    if len(positions) != 1:
        raise ValueError("Accession missing/duplicated in submissions cache")
    i = positions[0]
    if recent["primaryDocument"][i] != document or recent["form"][i] != "6-K":
        raise ValueError("Submissions document/form mismatch")
    utc = datetime.fromisoformat(recent["acceptanceDateTime"][i].replace("Z", "+00:00"))
    if utc.utcoffset().total_seconds() != 0:
        raise ValueError("Submissions acceptanceDateTime must have UTC offset")
    eastern = datetime.strptime(match[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("America/New_York"))
    if eastern.astimezone(timezone.utc) != utc:
        raise ValueError("SEC UTC and Eastern clocks disagree")
    return utc.astimezone(ZoneInfo("Asia/Taipei"))


def next_market_day(bound_date, days):
    future = sorted(day for day in days if day > bound_date)
    if not future:
        raise ValueError("Calendar does not cover next market day")
    return future[0]


def audit(config, root, calendar_root, fetch=False):
    submissions_text, submissions_meta = load_source(
        root, "sec_tsm_submissions", config["submissions_url"], fetch)
    submissions = json.loads(submissions_text)
    days = set()
    calendar_hashes = {}
    for month in config["calendar_months"]:
        path = calendar_root / f"calendar_{month}.json"
        raw = path.read_bytes()
        calendar_hashes[path.name] = hashlib.sha256(raw).hexdigest()
        payload = json.loads(raw)
        if payload.get("stat") != "OK" or not payload.get("data"):
            raise ValueError("Empty/error market calendar")
        for row in payload["data"]:
            year, mm, dd = map(int, row[0].split("/"))
            days.add(date(year + 1911, mm, dd))
    records = []
    for item in config["reports"]:
        sources = {}
        hashes = {"submissions": submissions_meta["sha256"]}
        for kind in ("issuer", "index", "filing"):
            sources[kind], meta = load_source(root, item[kind + "_cache"], item[kind + "_url"], fetch)
            hashes[kind] = meta["sha256"]
        issue_date = parse_issuer_date(sources["issuer"], item["revenue_month"])
        revenue, previous, yoy = parse_sec_revenue(sources["filing"], item["revenue_month"])
        accepted = reconcile_acceptance(sources["index"], submissions, item["accession"], item["document"])
        if accepted.date() < issue_date:
            raise ValueError("SEC acceptance precedes issuer issue date")
        bound = max(issue_date, accepted.date())
        record = {"symbol": "2330", "revenue_month": item["revenue_month"],
                  "revenue_twd_thousands": revenue, "previous_year_twd_thousands": previous,
                  "reported_yoy_pct": yoy, "issuer_publication_date": issue_date.isoformat(),
                  "issuer_timestamp_precision": "date", "sec_accepted_at": accepted.isoformat(),
                  "timing_basis": "issuer_date_and_sec_acceptance_next_market_day",
                  "candidate_available_date": next_market_day(bound, days).isoformat(),
                  "first_publication_timestamp_verified": False,
                  "complete_revision_history_verified": False,
                  "strict_ledger_eligible": False,
                  "source_url": item["filing_url"], "issuer_url": item["issuer_url"],
                  "acceptance_source_url": item["index_url"],
                  "snapshot_sha256": hashes["filing"], "source_hashes": hashes}
        records.append(record)
    return {"records": records, "calendar_sha256": calendar_hashes,
            "status": "source_pilot_only_not_model_input", "strict_ledger_rows": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/revenue_pilot.json")
    parser.add_argument("--cache", default="inputs/revenue_pilot")
    parser.add_argument("--calendar-root", default="twse_history/raw")
    parser.add_argument("--output", default="deliverables/revenue_source_pilot.json")
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    result = audit(json.loads(Path(args.config).read_text()), Path(args.cache),
                   Path(args.calendar_root), args.fetch)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"audited={len(result['records'])} strict_ledger_rows=0")


if __name__ == "__main__":
    main()
