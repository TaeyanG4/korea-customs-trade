#!/usr/bin/env python3
"""Validate every KCS country code against one small live API window."""
from __future__ import annotations

import argparse
import csv
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pilot  # noqa: E402


def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def text_first(root: ET.Element, name: str) -> str:
    for elem in root.iter():
        if strip_ns(elem.tag) == name:
            return (elem.text or "").strip()
    return ""


def inspect_response(content: bytes) -> dict[str, object]:
    root = ET.fromstring(content)
    result_code = text_first(root, "resultCode") or text_first(root, "returnReasonCode")
    result_msg = text_first(root, "resultMsg") or text_first(root, "returnAuthMsg") or text_first(root, "errMsg")
    item_count = 0
    fact_count = 0
    hs10_count = 0
    country_codes = set()
    for elem in root.iter():
        if strip_ns(elem.tag) != "item":
            continue
        item_count += 1
        d = {strip_ns(c.tag): (c.text or "").strip() for c in elem}
        ym = pilot.parse_year_month(d.get("year", ""))
        hs = d.get("hsCd", "")
        if ym and hs not in {"", "-"}:
            fact_count += 1
            if pilot.DIGITS10_RE.match(hs):
                hs10_count += 1
            if d.get("statCd"):
                country_codes.add(d["statCd"])
    return {
        "api_result_code": result_code,
        "api_result_msg": result_msg,
        "item_count": item_count,
        "fact_row_count": fact_count,
        "hs10_row_count": hs10_count,
        "returned_country_codes": ",".join(sorted(country_codes)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", default="data/reference/country_reference.csv")
    ap.add_argument("--month", default="202501", help="YYYYMM validation month")
    ap.add_argument("--output", default="data/reference/country_code_validation_202501.csv")
    ap.add_argument("--delay", type=float, default=0.15, help="seconds between requests")
    args = ap.parse_args()

    key = pilot.get_service_key(None)
    with Path(args.reference).open(encoding="utf-8", newline="") as f:
        countries = list(csv.DictReader(f))

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "country_code",
        "country_name_ko",
        "http_status",
        "api_result_code",
        "api_result_msg",
        "item_count",
        "fact_row_count",
        "hs10_row_count",
        "returned_country_codes",
        "validation_month",
    ]
    session = requests.Session()
    session.headers.update({"User-Agent": "korea-customs-trade-country-code-validator/0.1"})

    errors = 0
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, country in enumerate(countries, 1):
            code = country["country_code"]
            row = {
                "country_code": code,
                "country_name_ko": country["country_name_ko"],
                "http_status": "",
                "api_result_code": "",
                "api_result_msg": "",
                "item_count": 0,
                "fact_row_count": 0,
                "hs10_row_count": 0,
                "returned_country_codes": "",
                "validation_month": args.month,
            }
            try:
                r = session.get(
                    pilot.API_URL,
                    params={
                        "serviceKey": key,
                        "strtYymm": args.month,
                        "endYymm": args.month,
                        "cntyCd": code,
                    },
                    timeout=(10, 60),
                )
                row["http_status"] = r.status_code
                parsed = inspect_response(r.content)
                row.update(parsed)
                if r.status_code != 200 or parsed["api_result_code"] != "00":
                    errors += 1
            except Exception as exc:
                # Never stringify a requests prepared URL, which can contain serviceKey.
                row["api_result_msg"] = f"{type(exc).__name__}: validation request failed"
                errors += 1
            w.writerow(row)
            f.flush()
            if i % 25 == 0 or i == len(countries):
                print(f"progress={i}/{len(countries)} errors={errors}", flush=True)
            if args.delay:
                time.sleep(args.delay)

    print(f"validation_rows={len(countries)}")
    print(f"api_errors={errors}")
    print(f"output={out_path.resolve()}")
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
