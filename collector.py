#!/usr/bin/env python3
"""Production orchestration for Korea Customs country x HSK10 collection.

This module schedules the proven request engine in pilot.py across the official
KCS country reference, adds run-level manifests, stable-month boundaries,
checkpoint accounting, refresh mode, and safe handling for API quotas/rate limits.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import requests

import pilot


DEFAULT_START_MONTH = "201201"
DEFAULT_COUNTRY_REFERENCE = "data/reference/country_reference.csv"
AUTH_ERROR_CODES = {"20", "30", "31"}


def shift_month(yyyymm: str, delta: int) -> str:
    return pilot.index_to_yyyymm(pilot.yyyymm_to_index(yyyymm) + delta)


def latest_stable_month(today: date | None = None, publication_day: int = 15) -> str:
    """Conservative stable-month boundary for the KCS monthly revision cycle.

    KCS documents that prior-month data are refreshed around the 15th. Before
    that point we use two months back; after the 15th we use the prior month.
    """
    today = today or datetime.now().astimezone().date()
    this_month = f"{today.year:04d}{today.month:02d}"
    return shift_month(this_month, -1 if today.day > publication_day else -2)


def annual_windows(start_month: str, end_month: str) -> list[pilot.Window]:
    if pilot.yyyymm_to_index(end_month) < pilot.yyyymm_to_index(start_month):
        raise ValueError(f"end_month precedes start_month: {start_month} > {end_month}")
    months = pilot.months_in_window(pilot.Window(start_month, end_month))
    by_year: dict[str, list[str]] = {}
    for month in months:
        by_year.setdefault(month[:4], []).append(month)
    return [pilot.Window(ms[0], ms[-1]) for _, ms in sorted(by_year.items())]


def load_country_codes(path: Path, requested: list[str] | None = None) -> list[str]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    codes = [r["country_code"].strip().upper() for r in rows]
    if len(codes) != len(set(codes)):
        raise ValueError("country reference contains duplicate country_code values")
    if requested:
        wanted = [x.upper() for x in requested]
        unknown = sorted(set(wanted) - set(codes))
        if unknown:
            raise ValueError(f"unknown country codes: {','.join(unknown)}")
        return wanted
    return codes


def build_roots(
    countries: list[str],
    windows: list[pilot.Window],
    order: str = "year-country",
) -> list[tuple[str, pilot.Window]]:
    if order == "country-year":
        return [(c, w) for c in countries for w in windows]
    if order == "year-country":
        return [(c, w) for w in windows for c in countries]
    raise ValueError(f"unsupported order: {order}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def root_checkpoint_available(data_dir: Path, country: str, window: pilot.Window) -> bool:
    raw_path, manifest_path = pilot.request_paths(data_dir, country, window)
    return raw_path.exists() and pilot.load_completed(manifest_path) is not None


def root_collection_summary(
    country: str,
    window: pilot.Window,
    outcomes: list[pilot.RequestOutcome],
    checkpoint_reused: bool,
) -> dict:
    leaves = pilot.effective_leaf_outcomes(outcomes)
    successful = [o for o in leaves if o.success]
    failures = [o for o in leaves if not o.success]
    return {
        "country": country,
        "window_start": window.start,
        "window_end": window.end,
        "checkpoint_reused": checkpoint_reused,
        "collection_success": not failures and bool(leaves),
        "leaf_requests": len(leaves),
        "failed_leaf_requests": len(failures),
        "fact_row_count": sum(o.fact_row_count for o in successful),
        "non_hs10_fact_rows": sum(o.non_hs10_fact_rows for o in successful),
        "response_bytes": sum(o.response_bytes for o in successful),
        "gzip_bytes": sum(o.gzip_bytes for o in successful),
        "api_result_codes": sorted({o.api_result_code for o in leaves if o.api_result_code}),
        "statuses": sorted({o.status for o in leaves}),
        "failure_details": [
            {
                "window_start": o.window_start,
                "window_end": o.window_end,
                "status": o.status,
                "http_status": o.http_status,
                "api_result_code": o.api_result_code,
                "api_result_msg": o.api_result_msg,
            }
            for o in failures
        ],
    }


def contains_status(outcomes: Iterable[pilot.RequestOutcome], status: str) -> bool:
    return any(o.status == status for o in pilot.effective_leaf_outcomes(outcomes))


def contains_auth_failure(outcomes: Iterable[pilot.RequestOutcome]) -> bool:
    return any(
        o.status == "auth_error" or (o.api_result_code or "") in AUTH_ERROR_CODES
        for o in pilot.effective_leaf_outcomes(outcomes)
        if not o.success
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Production Korea Customs HSK10 collector")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--country-reference", default=DEFAULT_COUNTRY_REFERENCE)
    p.add_argument("--countries", nargs="+", default=None, help="optional subset for testing")
    p.add_argument("--order", choices=["year-country", "country-year"], default="year-country")
    p.add_argument("--request-delay", type=float, default=0.15)
    p.add_argument("--connect-timeout", type=float, default=10.0)
    p.add_argument("--read-timeout", type=float, default=180.0)
    p.add_argument("--retries", type=int, default=2)
    p.add_argument("--rate-limit-retries", type=int, default=4)
    p.add_argument("--max-roots", type=int, default=None, help="truncate plan for smoke tests")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="refetch even successful checkpoints")
    p.add_argument("--progress-every", type=int, default=25)

    sub = p.add_subparsers(dest="mode", required=True)
    backfill = sub.add_parser("backfill")
    backfill.add_argument("--start-month", default=DEFAULT_START_MONTH)
    backfill.add_argument("--end-month", default=None)

    refresh = sub.add_parser("refresh")
    refresh.add_argument("--end-month", default=None)
    refresh.add_argument(
        "--lookback-months",
        type=int,
        default=12,
        help="months before latest stable month to refetch; 12 means 13 inclusive months",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    stable = latest_stable_month()
    end_month = args.end_month or stable
    if args.mode == "backfill":
        start_month = args.start_month
        force = args.force
    else:
        start_month = shift_month(end_month, -args.lookback_months)
        force = True

    country_ref = Path(args.country_reference).resolve()
    data_dir = Path(args.data_dir).resolve()
    countries = load_country_codes(country_ref, args.countries)
    windows = annual_windows(start_month, end_month)
    roots = build_roots(countries, windows, args.order)
    if args.max_roots is not None:
        roots = roots[: args.max_roots]

    print(f"mode={args.mode}")
    print(f"stable_month={stable}")
    print(f"collection_range={start_month}-{end_month}")
    print(f"countries={len(countries)}")
    print(f"year_windows={len(windows)}")
    print(f"planned_roots={len(roots)}")
    if roots:
        print(f"first_root={roots[0][0]}:{roots[0][1].label}")
        print(f"last_root={roots[-1][0]}:{roots[-1][1].label}")
    if args.dry_run:
        return 0

    key = pilot.get_service_key(None)
    data_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "korea-customs-trade-collector/0.1 (+Kaggle dataset research)",
            "Accept": "application/xml,text/xml,*/*",
        }
    )

    started = datetime.now().astimezone()
    root_results = []
    stopped_reason = None
    try:
        for i, (country, window) in enumerate(roots, 1):
            checkpoint_reused = (not force) and root_checkpoint_available(data_dir, country, window)
            attempt = 0
            while True:
                outcomes = pilot.collect_with_split(
                    session=session,
                    service_key=key,
                    country=country,
                    window=window,
                    data_dir=data_dir,
                    connect_timeout=args.connect_timeout,
                    read_timeout=args.read_timeout,
                    retries=args.retries,
                    force=force or attempt > 0,
                    adaptive_split=True,
                    verbose=False,
                )
                if contains_status(outcomes, "rate_limited") and attempt < args.rate_limit_retries:
                    attempt += 1
                    sleep_s = min(2 ** attempt, 30)
                    print(f"rate_limited {country}:{window.label}; retrying in {sleep_s}s", file=sys.stderr)
                    time.sleep(sleep_s)
                    continue
                break

            result = root_collection_summary(country, window, outcomes, checkpoint_reused)
            result["rate_limit_retries"] = attempt
            root_results.append(result)

            if contains_status(outcomes, "quota_exceeded"):
                stopped_reason = "daily_quota_exceeded"
            elif contains_auth_failure(outcomes):
                stopped_reason = "authentication_or_permission_failure"
            elif contains_status(outcomes, "rate_limited"):
                stopped_reason = "rate_limit_retries_exhausted"

            if (
                i == 1
                or i % args.progress_every == 0
                or i == len(roots)
                or not result["collection_success"]
            ):
                print(
                    f"progress={i}/{len(roots)} root={country}:{window.label} "
                    f"success={result['collection_success']} rows={result['fact_row_count']} "
                    f"checkpoint={checkpoint_reused} non10={result['non_hs10_fact_rows']}",
                    flush=True,
                )

            if stopped_reason:
                print(f"stopping_reason={stopped_reason}", file=sys.stderr)
                break
            # Checkpoint reuse is a local disk operation and should not consume
            # API pacing budget. This makes interrupted full runs resume quickly.
            if args.request_delay and not checkpoint_reused:
                time.sleep(args.request_delay)
    except KeyboardInterrupt:
        stopped_reason = "interrupted"
        print("stopping_reason=interrupted; completed checkpoints are preserved", file=sys.stderr)

    finished = datetime.now().astimezone()
    successful_roots = [r for r in root_results if r["collection_success"]]
    failed_roots = [r for r in root_results if not r["collection_success"]]
    run = {
        "mode": args.mode,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "elapsed_seconds": round((finished - started).total_seconds(), 3),
        "stable_month_at_start": stable,
        "collection_start_month": start_month,
        "collection_end_month": end_month,
        "country_reference": str(country_ref),
        "country_reference_sha256": sha256_file(country_ref),
        "country_count": len(countries),
        "year_window_count": len(windows),
        "planned_roots": len(roots),
        "attempted_roots": len(root_results),
        "successful_roots": len(successful_roots),
        "failed_roots": len(failed_roots),
        "checkpoint_reused_roots": sum(r["checkpoint_reused"] for r in root_results),
        "no_trade_roots": sum(r["collection_success"] and r["fact_row_count"] == 0 for r in root_results),
        "fact_row_count": sum(r["fact_row_count"] for r in successful_roots),
        "non_hs10_fact_rows": sum(r["non_hs10_fact_rows"] for r in successful_roots),
        "response_bytes": sum(r["response_bytes"] for r in successful_roots),
        "gzip_bytes": sum(r["gzip_bytes"] for r in successful_roots),
        "stopped_reason": stopped_reason,
        "roots": root_results,
    }
    runs_dir = data_dir / "audits" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y%m%dT%H%M%S%z").replace("+", "p").replace("-", "m")
    run_path = runs_dir / f"collection_{args.mode}_{stamp}.json"
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"run_manifest={run_path}")
    print(
        f"run_summary success={len(successful_roots)}/{len(root_results)} "
        f"rows={run['fact_row_count']} checkpoints={run['checkpoint_reused_roots']} "
        f"failures={len(failed_roots)} stopped={stopped_reason or '-'}"
    )
    if stopped_reason:
        return 130 if stopped_reason == "interrupted" else 3
    if failed_roots:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
