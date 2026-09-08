#!/usr/bin/env python3
"""Build an annual revision-aware HSK10 reference from official KCS CLIP pages.

Network retrieval is intentionally separated from parsing through a gzip HTML
cache. CLIP currently interoperates more reliably with the system curl/SChannel
stack than with Python's OpenSSL stack on the Windows development host, so the
collector invokes curl and parses only cached bytes with BeautifulSoup.

The resulting reference is an *annual official CLIP edition*. It does not claim
to encode sub-annual legal amendment boundaries that CLIP does not expose in
its Korea year selector.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pyarrow as pa
import pyarrow.parquet as pq
from bs4 import BeautifulSoup


BASE_URL = "https://unipass.customs.go.kr/clip"
INDEX_URL = f"{BASE_URL}/hsinfosrch/retrieveBscsLst.do"
DETAIL_URL = f"{BASE_URL}/hsinfosrch/openULS0201005Q.do"
LANDING_URL = f"{BASE_URL}/hsinfosrch/openULS0201002Q.do?cntyCd=KR"
SOURCE_NAME = "Korea Customs Service CLIP annual tariff table"
HS10_RE = re.compile(r"^\d{10}$")
CHAPTER_RE = re.compile(r"^\d{2}$")


SCHEMA = pa.schema(
    [
        pa.field("reference_year", pa.int16(), nullable=False),
        pa.field("hs_revision", pa.string(), nullable=False),
        pa.field("valid_from", pa.string(), nullable=False),
        pa.field("valid_to", pa.string(), nullable=False),
        pa.field("clip_sct_year", pa.string(), nullable=True),
        pa.field("clip_hstd_year", pa.string(), nullable=True),
        pa.field("hs10", pa.string(), nullable=False),
        pa.field("hs8", pa.string(), nullable=False),
        pa.field("hs6", pa.string(), nullable=False),
        pa.field("hs4", pa.string(), nullable=False),
        pa.field("hs2", pa.string(), nullable=False),
        pa.field("name_ko", pa.string(), nullable=True),
        pa.field("name_en", pa.string(), nullable=True),
        pa.field("source", pa.string(), nullable=False),
        pa.field("source_url", pa.string(), nullable=False),
    ],
    metadata={
        b"dataset": b"South Korea Customs Trade - annual official HSK reference",
        b"revision_semantics": (
            b"HSK-YYYY denotes the official KCS CLIP annual tariff-table edition; "
            b"it is not a claim about sub-annual legal amendment boundaries"
        ),
    },
)


@dataclass(frozen=True)
class YearIndex:
    year: int
    clip_sct_year: str | None
    clip_hstd_year: str | None
    chapters: tuple[str, ...]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def text_of(node: Any) -> str | None:
    if node is None:
        return None
    value = " ".join(node.stripped_strings).strip()
    return value or None


def hidden_value(soup: BeautifulSoup, name: str) -> str | None:
    node = soup.find("input", attrs={"name": name})
    if node is None:
        return None
    value = str(node.get("value") or "").strip()
    return value or None


def parse_year_index(html: str, requested_year: int) -> YearIndex:
    soup = BeautifulSoup(html, "html.parser")
    returned_year = hidden_value(soup, "aplyYy")
    if returned_year and returned_year != str(requested_year):
        raise ValueError(f"CLIP returned year={returned_year}, requested={requested_year}")
    chapters = sorted(
        {
            str(node.get("value") or "").strip()
            for node in soup.find_all("input", attrs={"name": "hstdCd"})
            if CHAPTER_RE.fullmatch(str(node.get("value") or "").strip())
        }
    )
    if not chapters:
        raise ValueError(f"no chapter codes found for {requested_year}")
    return YearIndex(
        year=requested_year,
        clip_sct_year=hidden_value(soup, "sctYear"),
        clip_hstd_year=hidden_value(soup, "hstdYear"),
        chapters=tuple(chapters),
    )


def labels_compatible(a: str | None, b: str | None) -> bool:
    """Return True when two CLIP labels are identical or one expands the other."""
    aa = (a or "").strip()
    bb = (b or "").strip()
    if not aa or not bb or aa == bb:
        return True
    return aa.startswith(bb) or bb.startswith(aa)


def resolve_duplicate_row(
    previous: dict[str, Any],
    current: dict[str, Any],
    chapter: str,
    duplicate_audit: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Resolve duplicate CLIP labels without discarding source variants.

    Compatible wording variants keep the most descriptive label. If CLIP
    exposes genuinely different labels for the same exact HSK10 within one
    annual edition (observed at HS revision boundaries), preserve both labels
    in the audit and keep the first source-order definition provisionally.
    Adjacent-year QA determines whether it is a stale prior-edition duplicate.
    Structural/non-name conflicts still fail closed.
    """
    non_name_fields = [k for k in previous if k not in {"name_ko", "name_en"}]
    if any(previous[k] != current[k] for k in non_name_fields):
        raise ValueError(f"conflicting duplicate HSK10 {previous['hs10']} in chapter {chapter}")
    compatible = labels_compatible(previous.get("name_ko"), current.get("name_ko")) and labels_compatible(
        previous.get("name_en"), current.get("name_en")
    )

    def score(row: dict[str, Any]) -> tuple[int, int, int]:
        ko = row.get("name_ko") or ""
        en = row.get("name_en") or ""
        return (int(bool(ko)) + int(bool(en)), len(ko) + len(en), len(ko))

    selected = (current if score(current) > score(previous) else previous) if compatible else previous
    if duplicate_audit is not None:
        duplicate_audit.append(
            {
                "reference_year": previous["reference_year"],
                "chapter": chapter,
                "hs10": previous["hs10"],
                "name_ko_variants": sorted(
                    {x for x in [previous.get("name_ko"), current.get("name_ko")] if x}
                ),
                "name_en_variants": sorted(
                    {x for x in [previous.get("name_en"), current.get("name_en")] if x}
                ),
                "selected_name_ko": selected.get("name_ko"),
                "selected_name_en": selected.get("name_en"),
                "resolution": (
                    "prefer_more_specific_compatible_label"
                    if compatible
                    else "prefer_first_source_order_pending_adjacent_year_review"
                ),
            }
        )
    return selected


def parse_chapter_html(
    html: str,
    year_index: YearIndex,
    chapter: str,
    duplicate_audit: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: dict[str, dict[str, Any]] = {}
    for tr in soup.select("#tblLstBody tr"):
        code_node = tr.find("input", attrs={"name": "hsSgn_Mn"})
        code = str(code_node.get("value") or "").strip() if code_node else ""
        if not HS10_RE.fullmatch(code):
            continue
        if not code.startswith(chapter):
            raise ValueError(f"chapter {chapter} returned out-of-prefix HSK10 {code}")

        name_cells = tr.select("td.hlzoneWrd")
        name_ko = text_of(name_cells[0]) if len(name_cells) >= 1 else None
        name_en = text_of(name_cells[1]) if len(name_cells) >= 2 else None
        row = {
            "reference_year": year_index.year,
            "hs_revision": f"HSK-{year_index.year}",
            "valid_from": f"{year_index.year:04d}-01-01",
            "valid_to": f"{year_index.year:04d}-12-31",
            "clip_sct_year": year_index.clip_sct_year,
            "clip_hstd_year": year_index.clip_hstd_year,
            "hs10": code,
            "hs8": code[:8],
            "hs6": code[:6],
            "hs4": code[:4],
            "hs2": code[:2],
            "name_ko": name_ko,
            "name_en": name_en,
            "source": SOURCE_NAME,
            "source_url": LANDING_URL,
        }
        previous = rows.get(code)
        if previous is not None and previous != row:
            rows[code] = resolve_duplicate_row(previous, row, chapter, duplicate_audit)
        else:
            rows[code] = row
    return [rows[code] for code in sorted(rows)]


def find_curl() -> str:
    for name in ("curl.exe", "curl"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("curl was not found on PATH; install curl before collecting CLIP pages")


def curl_post(url: str, data: dict[str, str], timeout: int = 120) -> bytes:
    curl = find_curl()
    cmd = [
        curl,
        "-sS",
        "--fail-with-body",
        "--retry",
        "3",
        "--retry-delay",
        "2",
        "--connect-timeout",
        "15",
        "--max-time",
        str(timeout),
        "-A",
        "korea-customs-trade/0.1 (KCS CLIP reference research)",
        "-e",
        LANDING_URL,
        "-X",
        "POST",
        url,
    ]
    for key, value in data.items():
        cmd.extend(["--data-urlencode", f"{key}={value}"])
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"curl failed rc={proc.returncode}: {stderr}")
    if not proc.stdout:
        raise RuntimeError("CLIP returned an empty response body")
    return proc.stdout


def decode_html(payload: bytes) -> str:
    return payload.decode("utf-8", errors="strict")


def cache_read(path: Path) -> bytes:
    with gzip.open(path, "rb") as fh:
        return fh.read()


def cache_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wb", compresslevel=6) as fh:
        fh.write(payload)
    tmp.replace(path)


def fetch_cached(
    cache_path: Path,
    url: str,
    data: dict[str, str],
    force: bool,
) -> tuple[bytes, bool]:
    if cache_path.exists() and not force:
        return cache_read(cache_path), True
    payload = curl_post(url, data)
    cache_write(cache_path, payload)
    return payload, False


def base_form(year: int, index: YearIndex | None = None) -> dict[str, str]:
    return {
        "aplyYy": str(year),
        "cntyCd": "KR",
        "cntyNm": "한국",
        "hsSgn": "",
        "compareCrrspndNation": "KR",
        "sctYear": index.clip_sct_year if index and index.clip_sct_year else "",
        "hstdYear": index.clip_hstd_year if index and index.clip_hstd_year else "",
        "tabTpcd": "",
        "manlOrgnTpcd": "",
        "searchVal": "",
    }


def collect_year(
    year: int,
    source_root: Path,
    output_root: Path,
    force: bool,
    sleep_seconds: float,
    only_chapters: Iterable[str] | None = None,
) -> dict[str, Any]:
    year_cache = source_root / f"year={year}"
    index_path = year_cache / "index.html.gz"
    index_payload, index_cached = fetch_cached(
        index_path,
        INDEX_URL,
        base_form(year),
        force,
    )
    index = parse_year_index(decode_html(index_payload), year)
    selected_chapters = list(index.chapters)
    if only_chapters is not None:
        requested = set(only_chapters)
        unknown = requested - set(index.chapters)
        if unknown:
            raise ValueError(f"unknown chapter(s) for {year}: {sorted(unknown)}")
        selected_chapters = [c for c in index.chapters if c in requested]

    rows: dict[str, dict[str, Any]] = {}
    source_files: list[dict[str, Any]] = []
    duplicate_name_variants: list[dict[str, Any]] = []
    fetched = 0
    cached = int(index_cached)
    for seq, chapter in enumerate(selected_chapters, 1):
        path = year_cache / f"chapter={chapter}.html.gz"
        form = base_form(year, index)
        form["searchVal"] = chapter
        payload, was_cached = fetch_cached(path, DETAIL_URL, form, force)
        if was_cached:
            cached += 1
        else:
            fetched += 1
        chapter_rows = parse_chapter_html(
            decode_html(payload), index, chapter, duplicate_name_variants
        )
        for row in chapter_rows:
            code = row["hs10"]
            previous = rows.get(code)
            if previous is not None and previous != row:
                raise ValueError(f"conflicting duplicate HSK10 {code} across chapters")
            rows[code] = row
        source_files.append(
            {
                "chapter": chapter,
                "cache_path": str(path),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "hsk10_rows": len(chapter_rows),
                "cache_reused": was_cached,
            }
        )
        if seq == len(selected_chapters) or seq % 10 == 0:
            print(
                f"year={year} chapter_progress={seq}/{len(selected_chapters)} "
                f"hsk10={len(rows)} fetched={fetched} cached={cached}",
                flush=True,
            )
        if not was_cached and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    if not rows:
        raise RuntimeError(f"no HSK10 rows parsed for {year}")
    output_dir = output_root / f"year={year}"
    output_dir.mkdir(parents=True, exist_ok=True)
    is_full_year = set(selected_chapters) == set(index.chapters)
    if is_full_year:
        annual_path = output_dir / "hsk10.parquet"
    else:
        label = "-".join(selected_chapters)
        annual_path = output_dir / f"hsk10_probe_{label}.parquet"
    table = pa.Table.from_pylist([rows[k] for k in sorted(rows)], schema=SCHEMA)
    pq.write_table(table, annual_path, compression="zstd", compression_level=6, use_dictionary=True)
    return {
        "year": year,
        "clip_sct_year": index.clip_sct_year,
        "clip_hstd_year": index.clip_hstd_year,
        "chapter_count": len(selected_chapters),
        "full_year": is_full_year,
        "hsk10_rows": len(rows),
        "missing_name_ko": sum(not r["name_ko"] for r in rows.values()),
        "missing_name_en": sum(not r["name_en"] for r in rows.values()),
        "duplicate_name_variant_count": len(duplicate_name_variants),
        "duplicate_name_variants": duplicate_name_variants,
        "fetched_files": fetched,
        "cached_files": cached,
        "annual_parquet": str(annual_path),
        "annual_parquet_bytes": annual_path.stat().st_size,
        "source_files": source_files,
    }


def combine_annual(output_root: Path, years: Iterable[int], combined_path: Path) -> dict[str, Any]:
    tables = []
    counts: dict[str, int] = {}
    for year in years:
        path = output_root / f"year={year}" / "hsk10.parquet"
        if not path.exists():
            raise RuntimeError(f"missing annual HSK reference: {path}")
        table = pq.read_table(path)
        if not table.schema.equals(SCHEMA, check_metadata=False):
            raise RuntimeError(f"unexpected HSK reference schema: {path}")
        tables.append(table)
        counts[str(year)] = table.num_rows
    combined = pa.concat_tables(tables)
    keys = list(zip(combined["reference_year"].to_pylist(), combined["hs10"].to_pylist()))
    if len(keys) != len(set(keys)):
        raise RuntimeError("duplicate (reference_year, hs10) in combined HSK reference")
    combined_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(combined, combined_path, compression="zstd", compression_level=6, use_dictionary=True)
    return {
        "rows": combined.num_rows,
        "bytes": combined_path.stat().st_size,
        "year_rows": counts,
        "path": str(combined_path),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build annual official HSK reference from KCS CLIP")
    p.add_argument("--source-root", default="data/reference/source/hsk_clip")
    p.add_argument("--output-root", default="data/reference/hsk_codes")
    p.add_argument("--combined-output", default="data/reference/hsk_code_reference.parquet")
    p.add_argument("--audit-dir", default="data/audits/hsk_reference")
    sub = p.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="Fetch/parse one year and one chapter")
    probe.add_argument("--year", type=int, default=2022)
    probe.add_argument("--chapter", default="01")
    probe.add_argument("--force", action="store_true")

    collect = sub.add_parser("collect", help="Collect annual HSK reference editions")
    collect.add_argument("--start-year", type=int, default=2012)
    collect.add_argument("--end-year", type=int, default=2026)
    collect.add_argument("--sleep", type=float, default=0.20)
    collect.add_argument("--force", action="store_true")

    combine = sub.add_parser("combine", help="Combine already-built annual Parquet files")
    combine.add_argument("--start-year", type=int, default=2012)
    combine.add_argument("--end-year", type=int, default=2026)
    return p


def main() -> int:
    args = build_parser().parse_args()
    source_root = Path(args.source_root).resolve()
    output_root = Path(args.output_root).resolve()
    combined_path = Path(args.combined_output).resolve()
    audit_dir = Path(args.audit_dir).resolve()
    audit_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()

    if args.command == "probe":
        stat = collect_year(
            args.year,
            source_root,
            output_root,
            args.force,
            0.0,
            only_chapters=[args.chapter.zfill(2)],
        )
        print(json.dumps({k: v for k, v in stat.items() if k != "source_files"}, ensure_ascii=False, indent=2))
        return 0

    years = list(range(args.start_year, args.end_year + 1))
    if args.command == "combine":
        stat = combine_annual(output_root, years, combined_path)
        print(json.dumps(stat, ensure_ascii=False, indent=2))
        return 0

    year_stats = []
    for i, year in enumerate(years, 1):
        print(f"collect_year={year} progress={i}/{len(years)}", flush=True)
        year_stats.append(
            collect_year(year, source_root, output_root, args.force, args.sleep)
        )
    combined = combine_annual(output_root, years, combined_path)
    manifest = {
        "generated_at": utc_now(),
        "source": SOURCE_NAME,
        "source_url": LANDING_URL,
        "revision_policy": (
            "HSK-YYYY is the official KCS CLIP annual tariff-table edition. "
            "Sub-annual legal amendment boundaries are not inferred."
        ),
        "years": years,
        "year_stats": year_stats,
        "combined": combined,
        "elapsed_seconds": round(time.monotonic() - t0, 3),
    }
    manifest_path = audit_dir / "hsk_reference_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"combined_rows={combined['rows']}")
    print(f"combined_output={combined_path}")
    print(f"manifest={manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
