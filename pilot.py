#!/usr/bin/env python3
"""Pilot collector for Korea Customs item-by-country trade API.

Primary question answered by this pilot:
Does omitting hsSgn while supplying country + period return the full HSK10 universe?

Raw API responses are retained as gzip-compressed XML. Every request gets a JSON
manifest with request metadata, checksum, API status, and validation metrics.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote
import xml.etree.ElementTree as ET

import requests

API_URL = "https://apis.data.go.kr/1220000/nitemtrade/getNitemtradeList"
DEFAULT_COUNTRIES = ["US", "CN", "JP", "VN", "DE"]
DEFAULT_YEARS = [2012, 2017, 2022, 2025]
SPLITTABLE_HTTP = {408, 413, 429, 500, 502, 503, 504}
MONTH_RE = re.compile(r"^(\d{4})\.(\d{2})$")
DIGITS10_RE = re.compile(r"^\d{10}$")


@dataclass(frozen=True)
class Window:
    start: str  # YYYYMM
    end: str    # YYYYMM

    @property
    def label(self) -> str:
        return f"{self.start}-{self.end}"


@dataclass
class RequestOutcome:
    country: str
    window_start: str
    window_end: str
    split_level: str
    success: bool
    status: str
    http_status: int | None = None
    api_result_code: str | None = None
    api_result_msg: str | None = None
    row_count: int = 0
    fact_row_count: int = 0
    total_row_count: int = 0
    response_bytes: int = 0
    gzip_bytes: int = 0
    sha256: str | None = None
    elapsed_seconds: float = 0.0
    retry_count: int = 0
    raw_path: str | None = None
    manifest_path: str | None = None
    month_count: int = 0
    months_found: list[str] | None = None
    missing_months: list[str] | None = None
    hs_length_counts: dict[str, int] | None = None
    non_hs10_fact_rows: int = 0
    duplicate_key_rows: int = 0
    duplicate_key_groups: int = 0
    zero_trade_rows: int = 0
    negative_amount_or_weight_rows: int = 0
    balance_mismatch_rows: int = 0
    country_mismatch_rows: int = 0
    hs_name_variant_codes: int = 0
    hs_name_variant_examples: list[dict[str, Any]] | None = None
    parse_error: str | None = None
    exception: str | None = None
    parent_request: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_service_key(value: str) -> str:
    """Normalize either the encoded or decoded data.go.kr key for requests params."""
    value = value.strip()
    if not value:
        return value
    # data.go.kr commonly displays both Encoding and Decoding keys. requests will
    # URL-encode params itself, so decode an already-encoded key exactly once.
    return unquote(value)


def yyyymm_to_index(s: str) -> int:
    y, m = int(s[:4]), int(s[4:])
    return y * 12 + (m - 1)


def index_to_yyyymm(i: int) -> str:
    y, m0 = divmod(i, 12)
    return f"{y:04d}{m0 + 1:02d}"


def months_in_window(window: Window) -> list[str]:
    a, b = yyyymm_to_index(window.start), yyyymm_to_index(window.end)
    if b < a:
        raise ValueError(f"Invalid window: {window}")
    return [index_to_yyyymm(i) for i in range(a, b + 1)]


def split_window(window: Window) -> list[Window]:
    """Split year-ish -> quarters, quarter-ish -> months."""
    months = months_in_window(window)
    n = len(months)
    if n <= 1:
        return []
    if n > 3:
        chunks = [months[i:i + 3] for i in range(0, n, 3)]
    else:
        chunks = [[m] for m in months]
    return [Window(c[0], c[-1]) for c in chunks]


def window_level(window: Window) -> str:
    n = len(months_in_window(window))
    if n == 1:
        return "month"
    if n <= 3:
        return "quarter"
    if n <= 12:
        return "year"
    return "multi_year"


def strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def safe_text(elem: ET.Element, name: str) -> str:
    for child in elem:
        if strip_ns(child.tag) == name:
            return (child.text or "").strip()
    return ""


def as_int(text: str) -> int | None:
    t = (text or "").strip().replace(",", "")
    if t in {"", "-"}:
        return None
    try:
        return int(t)
    except ValueError:
        try:
            return int(float(t))
        except ValueError:
            return None


def parse_year_month(value: str) -> str | None:
    m = MONTH_RE.match((value or "").strip())
    if not m:
        return None
    return f"{m.group(1)}{m.group(2)}"


def parse_and_validate_gzip(path: Path, country: str, window: Window) -> dict[str, Any]:
    result_code = None
    result_msg = None
    gateway_reason_code = None
    gateway_auth_msg = None
    gateway_err_msg = None
    row_count = 0
    fact_row_count = 0
    total_row_count = 0
    months: set[str] = set()
    hs_lengths: Counter[str] = Counter()
    non_hs10_fact_rows = 0
    zero_trade_rows = 0
    negative_rows = 0
    balance_mismatch_rows = 0
    country_mismatch_rows = 0
    key_counts: Counter[tuple[str, str, str]] = Counter()
    hs_names: dict[str, set[str]] = defaultdict(set)

    with gzip.open(path, "rb") as fh:
        for _, elem in ET.iterparse(fh, events=("end",)):
            tag = strip_ns(elem.tag)
            if tag == "resultCode" and result_code is None:
                result_code = (elem.text or "").strip()
            elif tag == "resultMsg" and result_msg is None:
                result_msg = (elem.text or "").strip()
            elif tag == "returnReasonCode" and gateway_reason_code is None:
                gateway_reason_code = (elem.text or "").strip()
            elif tag == "returnAuthMsg" and gateway_auth_msg is None:
                gateway_auth_msg = (elem.text or "").strip()
            elif tag == "errMsg" and gateway_err_msg is None:
                gateway_err_msg = (elem.text or "").strip()
            elif tag == "item":
                row_count += 1
                year_raw = safe_text(elem, "year")
                ym = parse_year_month(year_raw)
                hs = safe_text(elem, "hsCd")
                stat_cd = safe_text(elem, "statCd")
                name_ko = safe_text(elem, "statKor")

                # The API commonly includes a total/summary item. Preserve it in raw
                # but exclude it from fact-level validation.
                if ym is None or hs in {"", "-"}:
                    total_row_count += 1
                    elem.clear()
                    continue

                fact_row_count += 1
                months.add(ym)
                hs_lengths[str(len(hs))] += 1
                if not DIGITS10_RE.match(hs):
                    non_hs10_fact_rows += 1

                key_counts[(ym, stat_cd, hs)] += 1
                if name_ko:
                    hs_names[hs].add(name_ko)

                if stat_cd and stat_cd != country:
                    country_mismatch_rows += 1

                exp_dlr = as_int(safe_text(elem, "expDlr"))
                exp_wgt = as_int(safe_text(elem, "expWgt"))
                imp_dlr = as_int(safe_text(elem, "impDlr"))
                imp_wgt = as_int(safe_text(elem, "impWgt"))
                bal = as_int(safe_text(elem, "balPayments"))
                values = [exp_dlr, exp_wgt, imp_dlr, imp_wgt]

                if all(v == 0 for v in values if v is not None) and all(v is not None for v in values):
                    zero_trade_rows += 1
                if any(v is not None and v < 0 for v in values):
                    negative_rows += 1
                if exp_dlr is not None and imp_dlr is not None and bal is not None:
                    if exp_dlr - imp_dlr != bal:
                        balance_mismatch_rows += 1

                elem.clear()

    duplicate_key_groups = sum(1 for c in key_counts.values() if c > 1)
    duplicate_key_rows = sum(c - 1 for c in key_counts.values() if c > 1)
    name_variants = [(hs, sorted(names)) for hs, names in hs_names.items() if len(names) > 1]
    expected_months = months_in_window(window)
    missing = sorted(set(expected_months) - months)

    # data.go.kr gateway errors are commonly returned as HTTP 200 XML under
    # cmmMsgHeader rather than the service's normal resultCode/resultMsg schema.
    # Normalize them into the same fields so quota/auth errors are actionable.
    if result_code is None and gateway_reason_code:
        result_code = gateway_reason_code
    if result_msg is None:
        result_msg = gateway_auth_msg or gateway_err_msg

    return {
        "api_result_code": result_code,
        "api_result_msg": result_msg,
        "row_count": row_count,
        "fact_row_count": fact_row_count,
        "total_row_count": total_row_count,
        "month_count": len(months),
        "months_found": sorted(months),
        "missing_months": missing,
        "hs_length_counts": dict(sorted(hs_lengths.items(), key=lambda kv: kv[0])),
        "non_hs10_fact_rows": non_hs10_fact_rows,
        "duplicate_key_rows": duplicate_key_rows,
        "duplicate_key_groups": duplicate_key_groups,
        "zero_trade_rows": zero_trade_rows,
        "negative_amount_or_weight_rows": negative_rows,
        "balance_mismatch_rows": balance_mismatch_rows,
        "country_mismatch_rows": country_mismatch_rows,
        "hs_name_variant_codes": len(name_variants),
        "hs_name_variant_examples": [
            {"hs10": hs, "names": names[:5]} for hs, names in name_variants[:20]
        ],
    }


def request_paths(data_dir: Path, country: str, window: Window) -> tuple[Path, Path]:
    year = window.start[:4]
    raw_dir = data_dir / "raw" / f"year={year}" / f"country={country}"
    manifest_dir = data_dir / "audits" / "manifests" / f"year={year}" / f"country={country}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"response_{window.label}.xml.gz"
    manifest_path = manifest_dir / f"request_{window.label}.json"
    return raw_path, manifest_path


def load_completed(manifest_path: Path) -> dict[str, Any] | None:
    if not manifest_path.exists():
        return None
    try:
        obj = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if obj.get("success") is True and obj.get("status") == "success":
        return obj
    return None


def save_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def download_one(
    session: requests.Session,
    service_key: str,
    country: str,
    window: Window,
    data_dir: Path,
    connect_timeout: float,
    read_timeout: float,
    retries: int,
    force: bool,
    parent_request: str | None = None,
) -> RequestOutcome:
    raw_path, manifest_path = request_paths(data_dir, country, window)
    if not force:
        completed = load_completed(manifest_path)
        if completed and raw_path.exists():
            fields = {k: v for k, v in completed.items() if k in RequestOutcome.__dataclass_fields__}
            return RequestOutcome(**fields)

    params = {
        "serviceKey": service_key,
        "strtYymm": window.start,
        "endYymm": window.end,
        "cntyCd": country,
        # hsSgn intentionally omitted: this is the central pilot hypothesis.
    }
    public_params = {k: v for k, v in params.items() if k != "serviceKey"}
    started_at = utc_now()
    t0 = time.monotonic()
    tmp_path = raw_path.with_suffix(raw_path.suffix + ".tmp")

    response_bytes = 0
    response_sha = None
    http_status = None
    content_type = None
    retry_count = 0

    for attempt in range(retries + 1):
        retry_count = attempt
        response = None
        sha = hashlib.sha256()
        attempt_bytes = 0
        tmp_path.unlink(missing_ok=True)
        try:
            response = session.get(
                API_URL,
                params=params,
                stream=True,
                timeout=(connect_timeout, read_timeout),
            )
            http_status = response.status_code
            content_type = response.headers.get("Content-Type")
            if response.status_code in SPLITTABLE_HTTP:
                raise requests.HTTPError(f"HTTP {response.status_code}", response=response)
            response.raise_for_status()

            # Keep the full body read inside the retry scope. Large XML can fail after
            # headers are received, so read-time errors must also be retried/split.
            with gzip.open(tmp_path, "wb", compresslevel=6) as gz:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    attempt_bytes += len(chunk)
                    sha.update(chunk)
                    gz.write(chunk)

            tmp_path.replace(raw_path)
            response_bytes = attempt_bytes
            response_sha = sha.hexdigest()
            break
        except requests.RequestException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            http_status = status_code if status_code is not None else http_status
            retryable = status_code is None or status_code in SPLITTABLE_HTTP
            exhausted = attempt >= retries or not retryable
            tmp_path.unlink(missing_ok=True)
            if exhausted:
                elapsed = time.monotonic() - t0
                status = "transport_error" if retryable else "http_error"
                outcome = RequestOutcome(
                    country=country,
                    window_start=window.start,
                    window_end=window.end,
                    split_level=window_level(window),
                    success=False,
                    status=status,
                    http_status=http_status,
                    elapsed_seconds=round(elapsed, 3),
                    retry_count=retry_count,
                    raw_path=str(raw_path),
                    manifest_path=str(manifest_path),
                    exception=f"{type(exc).__name__}: {exc}",
                    parent_request=parent_request,
                )
                manifest = asdict(outcome) | {
                    "requested_at": started_at,
                    "finished_at": utc_now(),
                    "endpoint": API_URL,
                    "request_params": public_params,
                    "hsSgn_omitted": True,
                }
                save_manifest(manifest_path, manifest)
                return outcome
            time.sleep(min(2 ** attempt, 8))
        finally:
            if response is not None:
                response.close()
    else:
        raise RuntimeError("download retry loop ended unexpectedly")

    gzip_bytes = raw_path.stat().st_size
    try:
        metrics = parse_and_validate_gzip(raw_path, country, window)
        parse_error = None
    except Exception as exc:
        # Raw data remains on disk even if parsing/validation fails.
        metrics = {}
        parse_error = f"{type(exc).__name__}: {exc}"

    elapsed = time.monotonic() - t0
    api_code = metrics.get("api_result_code")
    api_msg = (metrics.get("api_result_msg") or "").upper()
    api_ok = api_code == "00"
    parse_ok = parse_error is None
    success = bool(api_ok and parse_ok)
    daily_quota_exceeded = (
        api_code == "22"
        or "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS" in api_msg
    )
    if success:
        status = "success"
    elif not parse_ok:
        status = "parse_error"
    elif daily_quota_exceeded:
        status = "quota_exceeded"
    else:
        status = "api_error"
    outcome = RequestOutcome(
        country=country,
        window_start=window.start,
        window_end=window.end,
        split_level=window_level(window),
        success=success,
        status=status,
        http_status=http_status,
        response_bytes=response_bytes,
        gzip_bytes=gzip_bytes,
        sha256=response_sha,
        elapsed_seconds=round(elapsed, 3),
        retry_count=retry_count,
        raw_path=str(raw_path),
        manifest_path=str(manifest_path),
        parse_error=parse_error,
        parent_request=parent_request,
        **metrics,
    )
    manifest = asdict(outcome) | {
        "requested_at": started_at,
        "finished_at": utc_now(),
        "endpoint": API_URL,
        "request_params": public_params,
        "hsSgn_omitted": True,
        "response_content_type": content_type,
    }
    save_manifest(manifest_path, manifest)
    return outcome


def should_split(outcome: RequestOutcome) -> bool:
    if outcome.success:
        return False
    if outcome.split_level == "month":
        return False
    if outcome.status == "transport_error":
        return outcome.http_status is None or outcome.http_status in SPLITTABLE_HTTP
    # Do not mask authentication/parameter/API errors by splitting.
    return False


def collect_with_split(
    session: requests.Session,
    service_key: str,
    country: str,
    window: Window,
    data_dir: Path,
    connect_timeout: float,
    read_timeout: float,
    retries: int,
    force: bool,
    adaptive_split: bool,
    parent_request: str | None = None,
) -> list[RequestOutcome]:
    outcome = download_one(
        session=session,
        service_key=service_key,
        country=country,
        window=window,
        data_dir=data_dir,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        retries=retries,
        force=force,
        parent_request=parent_request,
    )
    print(
        f"[{country} {window.label}] {outcome.status} "
        f"rows={outcome.fact_row_count} bytes={outcome.response_bytes} "
        f"elapsed={outcome.elapsed_seconds:.1f}s"
    )
    if not adaptive_split or not should_split(outcome):
        return [outcome]

    children = split_window(window)
    if not children:
        return [outcome]
    print(f"  -> adaptive split: {window.label} into {len(children)} child window(s)")
    all_outcomes = [outcome]
    parent = f"{country}:{window.label}"
    for child in children:
        all_outcomes.extend(
            collect_with_split(
                session=session,
                service_key=service_key,
                country=country,
                window=child,
                data_dir=data_dir,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                retries=retries,
                force=force,
                adaptive_split=adaptive_split,
                parent_request=parent,
            )
        )
    return all_outcomes


def effective_leaf_outcomes(outcomes: Iterable[RequestOutcome]) -> list[RequestOutcome]:
    outcomes = list(outcomes)
    parents = {o.parent_request for o in outcomes if o.parent_request}
    # A failed parent that was split should not count as an unresolved leaf failure.
    return [o for o in outcomes if f"{o.country}:{o.window_start}-{o.window_end}" not in parents]


def summarize_hypothesis(outcome: RequestOutcome) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not outcome.success:
        return "INCONCLUSIVE", [f"request status={outcome.status}"]
    if outcome.fact_row_count == 0:
        reasons.append("no fact rows returned")
    if outcome.non_hs10_fact_rows:
        reasons.append(f"{outcome.non_hs10_fact_rows} fact rows are not 10-digit numeric HS")
    if outcome.missing_months:
        reasons.append(f"missing months: {','.join(outcome.missing_months)}")
    if outcome.duplicate_key_rows:
        reasons.append(f"duplicate extra rows: {outcome.duplicate_key_rows}")
    if outcome.country_mismatch_rows:
        reasons.append(f"country mismatch rows: {outcome.country_mismatch_rows}")
    if reasons:
        return "FAIL", reasons
    return "PASS", ["all returned fact rows are 10-digit HS; requested months covered; no duplicate keys"]


def logical_root_summary(
    country: str,
    window: Window,
    outcomes: list[RequestOutcome],
) -> dict[str, Any]:
    leaves_all = effective_leaf_outcomes(outcomes)
    leaves = [
        o for o in leaves_all
        if o.country == country and window.start <= o.window_start and o.window_end <= window.end
    ]
    if not leaves:
        return {
            "country": country,
            "window": window.label,
            "status": "missing",
            "verdict": "INCONCLUSIVE",
            "reasons": ["no request outcomes found"],
            "fact_row_count": 0,
            "response_bytes": 0,
            "month_count": 0,
            "missing_months": months_in_window(window),
            "hs_length_counts": {},
            "non_hs10_fact_rows": 0,
            "duplicate_key_rows": 0,
            "zero_trade_rows": 0,
            "negative_amount_or_weight_rows": 0,
            "balance_mismatch_rows": 0,
            "country_mismatch_rows": 0,
            "leaf_requests": 0,
        }

    unresolved = [o for o in leaves if not o.success]
    months = sorted({m for o in leaves if o.success for m in (o.months_found or [])})
    missing = sorted(set(months_in_window(window)) - set(months))
    hs_lengths: Counter[str] = Counter()
    for o in leaves:
        hs_lengths.update(o.hs_length_counts or {})

    fact_rows = sum(o.fact_row_count for o in leaves if o.success)
    non_hs10 = sum(o.non_hs10_fact_rows for o in leaves if o.success)
    dupes = sum(o.duplicate_key_rows for o in leaves if o.success)
    country_mismatch = sum(o.country_mismatch_rows for o in leaves if o.success)

    reasons: list[str] = []
    if unresolved:
        verdict = "INCONCLUSIVE"
        reasons.append(
            "unresolved leaf failures: "
            + ", ".join(f"{o.window_start}-{o.window_end}:{o.status}" for o in unresolved)
        )
    else:
        if fact_rows == 0:
            reasons.append("no fact rows returned")
        if non_hs10:
            reasons.append(f"{non_hs10} fact rows are not 10-digit numeric HS")
        if missing:
            reasons.append(f"missing months: {','.join(missing)}")
        if dupes:
            reasons.append(f"duplicate extra rows: {dupes}")
        if country_mismatch:
            reasons.append(f"country mismatch rows: {country_mismatch}")
        verdict = "FAIL" if reasons else "PASS"
        if not reasons:
            reasons.append("all effective leaf responses satisfy the HS10/month/key checks")

    root_exact = next(
        (
            o for o in outcomes
            if o.country == country
            and o.window_start == window.start
            and o.window_end == window.end
            and o.parent_request is None
        ),
        None,
    )
    if root_exact and root_exact.success:
        status = "success"
    elif not unresolved and leaves:
        status = "split_success"
    else:
        status = "failed"

    return {
        "country": country,
        "window": window.label,
        "status": status,
        "verdict": verdict,
        "reasons": reasons,
        "fact_row_count": fact_rows,
        "response_bytes": sum(o.response_bytes for o in leaves if o.success),
        "month_count": len(months),
        "missing_months": missing,
        "hs_length_counts": dict(sorted(hs_lengths.items())),
        "non_hs10_fact_rows": non_hs10,
        "duplicate_key_rows": dupes,
        "zero_trade_rows": sum(o.zero_trade_rows for o in leaves if o.success),
        "negative_amount_or_weight_rows": sum(
            o.negative_amount_or_weight_rows for o in leaves if o.success
        ),
        "balance_mismatch_rows": sum(o.balance_mismatch_rows for o in leaves if o.success),
        "country_mismatch_rows": country_mismatch,
        "leaf_requests": len(leaves),
    }


def iter_hs_name_observations(path: Path):
    with gzip.open(path, "rb") as fh:
        for _, elem in ET.iterparse(fh, events=("end",)):
            if strip_ns(elem.tag) != "item":
                continue
            ym = parse_year_month(safe_text(elem, "year"))
            hs = safe_text(elem, "hsCd")
            name = safe_text(elem, "statKor")
            if ym is not None and DIGITS10_RE.match(hs):
                yield ym, hs, name
            elem.clear()


def write_hs_name_audit(
    data_dir: Path,
    outcomes: list[RequestOutcome],
) -> tuple[Path, Path, int]:
    out_dir = data_dir / "audits" / "coverage"
    out_dir.mkdir(parents=True, exist_ok=True)
    inventory_path = out_dir / "hs_name_inventory.csv"
    changes_path = out_dir / "hs_name_changes.csv"

    inventory: dict[str, dict[str, Any]] = {}
    for o in effective_leaf_outcomes(outcomes):
        if not o.success or not o.raw_path:
            continue
        raw = Path(o.raw_path)
        if not raw.exists():
            continue
        for ym, hs, name in iter_hs_name_observations(raw):
            rec = inventory.setdefault(
                hs,
                {
                    "names": set(),
                    "years": set(),
                    "countries": set(),
                    "first_month": ym,
                    "last_month": ym,
                },
            )
            if name:
                rec["names"].add(name)
            rec["years"].add(ym[:4])
            rec["countries"].add(o.country)
            rec["first_month"] = min(rec["first_month"], ym)
            rec["last_month"] = max(rec["last_month"], ym)

    fields = [
        "hs10",
        "name_count",
        "names_json",
        "years_observed_json",
        "countries_observed_json",
        "first_trade_month_observed",
        "last_trade_month_observed",
    ]
    variant_count = 0
    with inventory_path.open("w", encoding="utf-8", newline="") as f_all, changes_path.open(
        "w", encoding="utf-8", newline=""
    ) as f_changes:
        wa = csv.DictWriter(f_all, fieldnames=fields)
        wc = csv.DictWriter(f_changes, fieldnames=fields)
        wa.writeheader()
        wc.writeheader()
        for hs in sorted(inventory):
            rec = inventory[hs]
            names = sorted(rec["names"])
            row = {
                "hs10": hs,
                "name_count": len(names),
                "names_json": json.dumps(names, ensure_ascii=False, separators=(",", ":")),
                "years_observed_json": json.dumps(sorted(rec["years"]), separators=(",", ":")),
                "countries_observed_json": json.dumps(sorted(rec["countries"]), separators=(",", ":")),
                "first_trade_month_observed": rec["first_month"],
                "last_trade_month_observed": rec["last_month"],
            }
            wa.writerow(row)
            if len(names) > 1:
                wc.writerow(row)
                variant_count += 1
    return inventory_path, changes_path, variant_count


def write_summary(
    data_dir: Path,
    outcomes: list[RequestOutcome],
    roots: list[tuple[str, Window]],
) -> tuple[Path, Path, Path, Path, Path]:
    out_dir = data_dir / "audits" / "coverage"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "pilot_results.json"
    csv_path = out_dir / "pilot_results.csv"
    report_path = out_dir / "pilot_report.md"

    json_path.write_text(
        json.dumps([asdict(o) for o in outcomes], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    rows = [asdict(o) for o in outcomes]
    fieldnames = list(RequestOutcome.__dataclass_fields__.keys())
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            row = row.copy()
            for key, value in list(row.items()):
                if isinstance(value, (list, dict)):
                    row[key] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            w.writerow(row)

    leaves = effective_leaf_outcomes(outcomes)
    unresolved = [o for o in leaves if not o.success]
    successful = [o for o in leaves if o.success]
    total_fact = sum(o.fact_row_count for o in successful)
    total_bytes = sum(o.response_bytes for o in successful)
    hs10_bad = sum(o.non_hs10_fact_rows for o in successful)
    dupes = sum(o.duplicate_key_rows for o in successful)

    inventory_path, changes_path, variant_count = write_hs_name_audit(data_dir, outcomes)
    root_summaries = [logical_root_summary(country, window, outcomes) for country, window in roots]

    lines = [
        "# Korea Customs API Pilot Report",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Run summary",
        "",
        f"- Logical country-year roots: {len(roots)}",
        f"- Effective leaf requests: {len(leaves)}",
        f"- Successful leaf requests: {len(successful)}",
        f"- Unresolved leaf failures: {len(unresolved)}",
        f"- Fact rows parsed: {total_fact:,}",
        f"- Uncompressed XML bytes: {total_bytes:,}",
        f"- Non-HSK10 fact rows: {hs10_bad:,}",
        f"- Duplicate extra rows: {dupes:,}",
        f"- HSK10 codes with >1 observed Korean item name: {variant_count:,}",
        "",
        "## Logical country-year checks",
        "",
        "| country | window | status | leaf reqs | fact rows | HS lengths | months | missing | hypothesis |",
        "|---|---|---:|---:|---:|---|---:|---|---|",
    ]
    for r in root_summaries:
        lines.append(
            f"| {r['country']} | {r['window']} | {r['status']} | {r['leaf_requests']} | "
            f"{r['fact_row_count']:,} | `{json.dumps(r['hs_length_counts'], ensure_ascii=False)}` | "
            f"{r['month_count']} | {','.join(r['missing_months']) or '-'} | "
            f"{r['verdict']}: {'; '.join(r['reasons'])} |"
        )

    lines += [
        "",
        "## Name/code observation audit",
        "",
        f"- Inventory: `{inventory_path.name}`",
        f"- Multiple-name observations: `{changes_path.name}`",
        "- These files describe codes and names observed in trade rows only. A code missing from a "
        "pilot year may simply have had no trade; this is not a substitute for official HSK validity codebooks.",
        "",
        "## Interpretation rule",
        "",
        "The central hypothesis is accepted for a logical country-year only when all effective leaf "
        "requests succeed, at least one fact row is returned, every fact row has a numeric 10-digit HS "
        "code, the requested months are represented, and `(month, country, hs10)` contains no duplicates.",
        "",
        "A PASS proves the observed behavior for that country-year. It does not by itself prove that "
        "every historically valid HSK10 code is returned; later reconciliation against independent "
        "official aggregates/codebooks is still required.",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, csv_path, report_path, inventory_path, changes_path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Korea Customs HS10 country-year pilot")
    p.add_argument("--data-dir", default="data", help="Output root (default: data)")
    p.add_argument("--service-key", default=None, help="data.go.kr service key; prefer env var")
    p.add_argument("--connect-timeout", type=float, default=10.0)
    p.add_argument("--read-timeout", type=float, default=180.0)
    p.add_argument("--retries", type=int, default=2)
    p.add_argument("--force", action="store_true", help="Ignore successful checkpoints and refetch")
    p.add_argument("--no-adaptive-split", action="store_true")

    sub = p.add_subparsers(dest="command", required=True)
    quick = sub.add_parser("quick", help="Run one country-year; default US 2025")
    quick.add_argument("--country", default="US")
    quick.add_argument("--year", type=int, default=2025)

    matrix = sub.add_parser("matrix", help="Run the planned 5-country x 4-year pilot")
    matrix.add_argument("--countries", nargs="+", default=DEFAULT_COUNTRIES)
    matrix.add_argument("--years", nargs="+", type=int, default=DEFAULT_YEARS)
    return p


def get_service_key(cli_value: str | None) -> str:
    raw = (
        cli_value
        or os.getenv("KCS_SERVICE_KEY")
        or os.getenv("DATA_GO_KR_SERVICE_KEY")
        or os.getenv("SERVICE_KEY")
    )
    if not raw:
        raise SystemExit(
            "Missing service key. Set KCS_SERVICE_KEY (recommended) or pass --service-key.\n"
            "Example (PowerShell): $env:KCS_SERVICE_KEY='YOUR_KEY'"
        )
    return normalize_service_key(raw)


def main() -> int:
    args = build_parser().parse_args()
    key = get_service_key(args.service_key)
    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "korea-customs-trade-pilot/0.1 (+Kaggle dataset research)",
        "Accept": "application/xml,text/xml,*/*",
    })

    roots: list[tuple[str, Window]] = []
    if args.command == "quick":
        roots.append((args.country.upper(), Window(f"{args.year}01", f"{args.year}12")))
    else:
        for country in args.countries:
            for year in args.years:
                roots.append((country.upper(), Window(f"{year}01", f"{year}12")))

    outcomes: list[RequestOutcome] = []
    attempted_roots: list[tuple[str, Window]] = []
    quota_exceeded = False
    for country, window in roots:
        attempted_roots.append((country, window))
        root_outcomes = collect_with_split(
            session=session,
            service_key=key,
            country=country,
            window=window,
            data_dir=data_dir,
            connect_timeout=args.connect_timeout,
            read_timeout=args.read_timeout,
            retries=args.retries,
            force=args.force,
            adaptive_split=not args.no_adaptive_split,
        )
        outcomes.extend(root_outcomes)
        if any(o.status == "quota_exceeded" for o in root_outcomes):
            quota_exceeded = True
            print(
                "Daily data.go.kr request quota exceeded; stopping immediately and preserving "
                "checkpoints. Re-run later to resume from successful manifests.",
                file=sys.stderr,
            )
            break

    json_path, csv_path, report_path, inventory_path, changes_path = write_summary(
        data_dir, outcomes, attempted_roots
    )
    leaves = effective_leaf_outcomes(outcomes)
    failures = [o for o in leaves if not o.success]
    print(f"\nsummary_json={json_path}")
    print(f"summary_csv={csv_path}")
    print(f"report={report_path}")
    print(f"hs_name_inventory={inventory_path}")
    print(f"hs_name_changes={changes_path}")
    if quota_exceeded:
        return 3
    if failures:
        print(f"unresolved_failures={len(failures)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
