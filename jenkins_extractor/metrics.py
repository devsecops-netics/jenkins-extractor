"""Agregaciones de tasa de éxito.

Definición: success_rate = SUCCESS / (SUCCESS + FAILURE + UNSTABLE).
ABORTED, NOT_BUILT e IN_PROGRESS se informan pero quedan fuera del denominador.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Callable, Iterable

from .extract import Build

RATE_RESULTS = ("SUCCESS", "FAILURE", "UNSTABLE")
COUNT_FIELDS = ("success", "failure", "unstable", "aborted", "not_built", "in_progress")
SUCCESS_RATE_DEFINITION = "SUCCESS / (SUCCESS + FAILURE + UNSTABLE); ABORTED, NOT_BUILT e IN_PROGRESS excluidos"


def success_rate(counts: Counter) -> float | None:
    denom = sum(counts[r] for r in RATE_RESULTS)
    return round(counts["SUCCESS"] / denom, 4) if denom else None


def percentile(values: list[float], q: float) -> float | None:
    """Percentil por nearest-rank."""
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, math.ceil(q * len(ordered)) - 1)
    return round(ordered[idx], 3)


def _counts_row(items: list[Build]) -> dict:
    counts = Counter(b.result for b in items)
    durations = [b.duration_s for b in items if b.result in RATE_RESULTS]
    row = {"total_builds": len(items)}
    row.update({f: counts[f.upper()] for f in COUNT_FIELDS})
    row["success_rate"] = success_rate(counts)
    row["duration_avg_s"] = round(sum(durations) / len(durations), 3) if durations else None
    row["duration_p50_s"] = percentile(durations, 0.50)
    row["duration_p95_s"] = percentile(durations, 0.95)
    return row


def _group(builds: Iterable[Build], key: Callable[[Build], tuple]) -> dict[tuple, list[Build]]:
    groups: dict[tuple, list[Build]] = defaultdict(list)
    for b in builds:
        groups[key(b)].append(b)
    return groups


def summary_by_job(builds: list[Build]) -> list[dict]:
    rows = []
    for (job, folder, job_type, branch), items in sorted(
        _group(builds, lambda b: (b.job_full_name, b.folder, b.job_type, b.branch)).items()
    ):
        items.sort(key=lambda b: b.timestamp_ms)
        completed = [b for b in items if b.result != "IN_PROGRESS"]
        row = {"job_full_name": job, "folder": folder, "job_type": job_type, "branch": branch}
        row.update(_counts_row(items))
        row["first_build_at_utc"] = items[0].started_at_utc
        row["last_build_at_utc"] = items[-1].started_at_utc
        row["last_result"] = completed[-1].result if completed else None
        rows.append(row)
    return rows


def daily_by_job(builds: list[Build]) -> list[dict]:
    rows = []
    for (date, job, folder), items in sorted(
        _group(builds, lambda b: (b.started_date, b.job_full_name, b.folder)).items()
    ):
        row = {"date": date, "job_full_name": job, "folder": folder}
        row.update(_counts_row(items))
        rows.append(row)
    return rows


def daily_global(builds: list[Build]) -> list[dict]:
    rows = []
    for (date,), items in sorted(_group(builds, lambda b: (b.started_date,)).items()):
        row = {"date": date, "jobs_with_builds": len({b.job_full_name for b in items})}
        row.update(_counts_row(items))
        rows.append(row)
    return rows


SUMMARY_FIELDS = (
    ["job_full_name", "folder", "job_type", "branch", "total_builds", *COUNT_FIELDS, "success_rate"]
    + ["duration_avg_s", "duration_p50_s", "duration_p95_s"]
    + ["first_build_at_utc", "last_build_at_utc", "last_result"]
)
DAILY_JOB_FIELDS = (
    ["date", "job_full_name", "folder", "total_builds", *COUNT_FIELDS, "success_rate"]
    + ["duration_avg_s", "duration_p50_s", "duration_p95_s"]
)
DAILY_GLOBAL_FIELDS = (
    ["date", "jobs_with_builds", "total_builds", *COUNT_FIELDS, "success_rate"]
    + ["duration_avg_s", "duration_p50_s", "duration_p95_s"]
)
