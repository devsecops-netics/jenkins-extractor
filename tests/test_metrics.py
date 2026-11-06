from collections import Counter

from jenkins_extractor import metrics
from jenkins_extractor.extract import Build


def mk(job, n, result, date="2026-11-01", dur=10.0, ts=0):
    return Build(job, "", "", "pipeline", n, result, result == "IN_PROGRESS", "", date, ts or n, dur, "", "", "", "")


def test_success_rate_excludes_aborted_and_in_progress():
    c = Counter({"SUCCESS": 3, "FAILURE": 1, "ABORTED": 5, "IN_PROGRESS": 2})
    assert metrics.success_rate(c) == 0.75
    assert metrics.success_rate(Counter({"ABORTED": 1})) is None


def test_percentile_nearest_rank():
    assert metrics.percentile([], 0.95) is None
    assert metrics.percentile([1, 2, 3, 4], 0.5) == 2
    assert metrics.percentile(list(range(1, 101)), 0.95) == 95


def test_summary_and_daily():
    builds = [
        mk("a", 1, "SUCCESS", "2026-11-01", 10),
        mk("a", 2, "FAILURE", "2026-11-02", 30),
        mk("a", 3, "IN_PROGRESS", "2026-11-02", 0),
        mk("b", 1, "UNSTABLE", "2026-11-02", 20),
    ]
    by_job = {r["job_full_name"]: r for r in metrics.summary_by_job(builds)}
    assert by_job["a"]["success_rate"] == 0.5
    assert by_job["a"]["duration_avg_s"] == 20.0  # in_progress no cuenta en duración
    assert by_job["a"]["last_result"] == "FAILURE"
    glob = {r["date"]: r for r in metrics.daily_global(builds)}
    assert glob["2026-11-02"]["jobs_with_builds"] == 2
    assert glob["2026-11-02"]["success_rate"] == 0.0
    assert len(metrics.daily_by_job(builds)) == 3
