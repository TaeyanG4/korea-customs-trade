#!/usr/bin/env python3
"""Build the official Korea Customs country-code reference.

KCS is authoritative for country_code and country_name_ko. UN M49 is used only
to enrich exact current ISO-alpha2 matches with English/M49/alpha3 fields.
Unmatched KCS historical/special codes are retained unchanged.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup


KCS_PAGE_URL = "https://www.data.go.kr/data/15101630/openapi.do?recommendDataYn=Y"
KCS_FILE_DOWNLOAD = "https://www.data.go.kr/cmm/cmm/fileDownload.do"
UN_M49_URL = "https://unstats.un.org/unsd/methodology/m49/overview/"

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def discover_and_download_kcs(session: requests.Session, source_dir: Path) -> tuple[Path, dict]:
    r = session.get(KCS_PAGE_URL, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    candidates = []
    for div in soup.select(".file-name"):
        name = div.get_text(strip=True)
        if "관세청조회코드" not in name or not name.lower().endswith(".xlsx"):
            continue
        container = div.find_parent("li") or div.parent
        button = container.find("button", onclick=True) if container else None
        onclick = button.get("onclick", "") if button else ""
        m = re.search(r"fn_fileDownload\('([^']+)'\s*,\s*'([^']+)'\)", onclick)
        if m:
            candidates.append((name, m.group(1), m.group(2)))
    if not candidates:
        raise RuntimeError("Could not discover the KCS lookup-code XLSX attachment")

    name, attachment_id, file_detail_sn = candidates[0]
    version_match = re.search(r"v([0-9.]+)", name, re.I)
    version = version_match.group(1) if version_match else "unknown"
    download_url = (
        f"{KCS_FILE_DOWNLOAD}?atchFileId={attachment_id}&fileDetailSn={file_detail_sn}"
    )
    resp = session.get(download_url, timeout=60)
    resp.raise_for_status()
    if not resp.content.startswith(b"PK\x03\x04"):
        raise RuntimeError("KCS reference download is not an XLSX/ZIP payload")

    source_dir.mkdir(parents=True, exist_ok=True)
    path = source_dir / f"kcs_lookup_codes_v{version}.xlsx"
    path.write_bytes(resp.content)
    meta = {
        "page_url": KCS_PAGE_URL,
        "download_url": download_url,
        "attachment_id": attachment_id,
        "file_detail_sn": file_detail_sn,
        "source_filename": name,
        "version": version,
        "local_path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    return path, meta


def _shared_strings(z: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    ns = f"{{{MAIN_NS}}}"
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(ns + "t")) for si in root.findall(ns + "si")]


def _sheet_target(z: ZipFile, sheet_name: str) -> str:
    ns = {"m": MAIN_NS, "r": REL_NS}
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rid = None
    for sheet in wb.find("m:sheets", ns):
        if sheet.attrib.get("name") == sheet_name:
            rid = sheet.attrib.get(f"{{{REL_NS}}}id")
            break
    if not rid:
        raise RuntimeError(f"Worksheet not found: {sheet_name}")

    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.findall(f"{{{PKG_REL_NS}}}Relationship"):
        if rel.attrib.get("Id") == rid:
            target = rel.attrib["Target"].lstrip("/")
            return target if target.startswith("xl/") else f"xl/{target}"
    raise RuntimeError(f"Worksheet relationship not found: {sheet_name} / {rid}")


def _cell_value(cell: ET.Element, shared: list[str]) -> str:
    ns = f"{{{MAIN_NS}}}"
    typ = cell.attrib.get("t")
    v = cell.find(ns + "v")
    if typ == "s" and v is not None:
        return shared[int(v.text)]
    if typ == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(ns + "t"))
    return (v.text or "") if v is not None else ""


def extract_kcs_countries(path: Path) -> list[dict[str, str]]:
    ns = f"{{{MAIN_NS}}}"
    with ZipFile(path) as z:
        shared = _shared_strings(z)
        target = _sheet_target(z, "국가코드")
        root = ET.fromstring(z.read(target))
        parsed = []
        for row in root.iter(ns + "row"):
            vals: dict[str, str] = {}
            for cell in row.findall(ns + "c"):
                ref = cell.attrib.get("r", "")
                m = re.match(r"[A-Z]+", ref)
                if m:
                    vals[m.group(0)] = _cell_value(cell, shared).strip()
            if vals:
                parsed.append((int(row.attrib.get("r", "0")), vals))

    header_index = None
    for i, (_, vals) in enumerate(parsed):
        if vals.get("A") == "국가코드" and vals.get("B") == "국가명":
            header_index = i
            break
    if header_index is None:
        raise RuntimeError("Could not locate 국가코드/국가명 header in KCS workbook")

    rows = []
    for source_row, vals in parsed[header_index + 1 :]:
        code = vals.get("A", "").strip()
        name = vals.get("B", "").strip()
        if not code and not name:
            continue
        rows.append({"country_code": code, "country_name_ko": name, "kcs_source_row": str(source_row)})
    return rows


def fetch_un_m49(session: requests.Session) -> tuple[dict[str, dict[str, str]], dict]:
    r = session.get(UN_M49_URL, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table", id="downloadTableEN")
    if table is None:
        raise RuntimeError("UN M49 English download table not found")
    trs = table.find_all("tr")
    headers = [x.get_text(" ", strip=True) for x in trs[0].find_all(["th", "td"])]
    idx = {h: i for i, h in enumerate(headers)}
    needed = ["Country or Area", "M49 Code", "ISO-alpha2 Code", "ISO-alpha3 Code"]
    if any(k not in idx for k in needed):
        raise RuntimeError(f"Unexpected UN M49 headers: {headers}")

    mapping: dict[str, dict[str, str]] = {}
    for tr in trs[1:]:
        cells = [x.get_text(" ", strip=True) for x in tr.find_all("td")]
        if len(cells) < len(headers):
            continue
        alpha2 = cells[idx["ISO-alpha2 Code"]].strip()
        if not alpha2:
            continue
        mapping[alpha2] = {
            "country_name_en": cells[idx["Country or Area"]].strip(),
            "un_m49": cells[idx["M49 Code"]].strip(),
            "iso_alpha3": cells[idx["ISO-alpha3 Code"]].strip(),
        }
    meta = {"url": UN_M49_URL, "rows_with_alpha2": len(mapping)}
    return mapping, meta


def build_reference(kcs_rows: list[dict[str, str]], un_map: dict[str, dict[str, str]], version: str):
    seen = set()
    out = []
    for row in kcs_rows:
        code = row["country_code"]
        if len(code) != 2:
            raise ValueError(f"KCS country code is not length 2: {code!r}")
        if code in seen:
            raise ValueError(f"Duplicate KCS country code: {code}")
        if not row["country_name_ko"]:
            raise ValueError(f"Missing Korean country name: {code}")
        seen.add(code)
        un = un_map.get(code, {})
        out.append(
            {
                "country_code": code,
                "country_name_ko": row["country_name_ko"],
                "country_name_en": un.get("country_name_en", ""),
                "un_m49": un.get("un_m49", ""),
                "iso_alpha3": un.get("iso_alpha3", ""),
                "un_match_status": "matched_current_un" if un else "unmatched_kcs_code",
                "kcs_source_version": version,
                "kcs_source_row": row["kcs_source_row"],
            }
        )
    return out


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-dir", default="data/reference/source")
    ap.add_argument("--output", default="data/reference/country_reference.csv")
    ap.add_argument("--manifest", default="data/reference/source_manifest.json")
    args = ap.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": "korea-customs-trade-reference-builder/0.1"})
    kcs_path, kcs_meta = discover_and_download_kcs(session, Path(args.source_dir))
    kcs_rows = extract_kcs_countries(kcs_path)
    un_map, un_meta = fetch_un_m49(session)
    rows = build_reference(kcs_rows, un_map, kcs_meta["version"])
    write_csv(Path(args.output), rows)

    unmatched = [r["country_code"] for r in rows if r["un_match_status"] != "matched_current_un"]
    manifest = {
        "generated_at": utc_now(),
        "authority_policy": {
            "country_code_and_korean_name": "Korea Customs Service lookup-code workbook",
            "english_name_and_un_codes": "UN Statistics Division M49 exact alpha-2 matches only",
            "unmatched_policy": "retain KCS row unchanged; do not infer English name",
        },
        "kcs": kcs_meta | {"country_rows": len(kcs_rows)},
        "un_m49": un_meta,
        "output": {
            "path": args.output,
            "rows": len(rows),
            "matched_current_un": len(rows) - len(unmatched),
            "unmatched_kcs_codes": unmatched,
        },
    }
    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"country_rows={len(rows)}")
    print(f"matched_current_un={len(rows) - len(unmatched)}")
    print(f"unmatched_kcs_codes={len(unmatched)}:{','.join(unmatched)}")
    print(f"country_reference={Path(args.output).resolve()}")
    print(f"source_manifest={manifest_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
