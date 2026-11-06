import csv
import json
from datetime import datetime, timezone

from jenkins_extractor.__main__ import main
from jenkins_extractor.client import JenkinsClient
from jenkins_extractor.config import Config
from jenkins_extractor.extract import classify_job_type, discover_jobs, extract_all, job_path

from conftest import NOW_MS

NOW = datetime.fromtimestamp(NOW_MS / 1000, tz=timezone.utc)


def test_job_path_encodes_multibranch_names():
    assert job_path("team/svc/feature%2Flogin") == "job/team/job/svc/job/feature%252Flogin/"
    assert job_path("a b") == "job/a%20b/"


def test_classify_job_type():
    mb = "org.jenkinsci.plugins.workflow.multibranch.WorkflowMultiBranchProject"
    assert classify_job_type("x.WorkflowJob", mb) == "multibranch-branch"
    assert classify_job_type("org.jenkinsci.plugins.workflow.job.WorkflowJob", None) == "pipeline"
    assert classify_job_type("hudson.model.FreeStyleProject", None) == "freestyle"


def test_discovery_recurses_folders_and_multibranch(fake_jenkins):
    client = JenkinsClient(Config.from_env())
    jobs = {j.full_name: j for j in discover_jobs(client)}
    assert set(jobs) == {"freestyle-app", "team/=evil", "team/svc/main", "team/svc/feature%2Flogin"}
    assert jobs["team/svc/feature%2Flogin"].branch == "feature/login"
    assert jobs["team/svc/main"].folder == "team/svc"


def test_extract_all_window_errors_and_causes(fake_jenkins):
    cfg = Config.from_env(lookback_days=30)
    res = extract_all(JenkinsClient(cfg), cfg, now=NOW)
    nums = [(b.job_full_name, b.number) for b in res.builds]
    assert ("freestyle-app", 1) not in nums  # fuera de ventana
    assert len(res.builds) == 6
    assert res.errors and res.errors[0]["job"] == "team/svc/feature%2Flogin"
    fs = {b.number: b for b in res.builds if b.job_full_name == "freestyle-app"}
    assert fs[4].result == "IN_PROGRESS"
    assert fs[3].trigger == "timer"
    assert fs[2].trigger_user == ""  # usuarios no se extraen por defecto
    assert fs[2].built_on == "built-in"


def test_tree_query_is_used(fake_jenkins):
    _, handler = fake_jenkins
    cfg = Config.from_env()
    extract_all(JenkinsClient(cfg), cfg, now=NOW)
    trees = [q.get("tree", [""])[0] for p, q in handler.requests_seen]
    assert all(trees), "todas las llamadas deben limitar campos con tree="
    assert any(t.startswith("allBuilds[") and t.endswith("{0,500}") for t in trees)


def test_cli_end_to_end(fake_jenkins, tmp_path, monkeypatch):
    # el CLI usa now real: correr con ventana amplia
    rc = main(["--output", str(tmp_path), "--lookback-days", "100000", "--strict"])
    assert rc == 1  # hay un job con error y --strict
    files = {p.name for p in tmp_path.iterdir()}
    assert files == {
        "jobs.csv", "builds.csv", "success_rate_by_job.csv",
        "success_rate_daily_by_job.csv", "success_rate_daily.csv", "metadata.json",
    }
    meta = json.loads((tmp_path / "metadata.json").read_text())
    assert meta["jenkins_version"] == "2.479.1" and meta["builds"] == 7
    assert "tok" not in (tmp_path / "metadata.json").read_text()

    with open(tmp_path / "success_rate_by_job.csv", encoding="utf-8-sig") as fh:
        rows = {r["job_full_name"]: r for r in csv.DictReader(fh)}
    fs = rows["freestyle-app"]
    assert (fs["success"], fs["failure"], fs["in_progress"]) == ("2", "1", "1")
    assert fs["success_rate"] == "0.6667"
    assert rows["team/=evil"]["success_rate"] == ""  # solo ABORTED -> sin tasa

    with open(tmp_path / "jobs.csv", encoding="utf-8-sig") as fh:
        names = {r["name"] for r in csv.DictReader(fh)}
    assert "'=evil" in names  # mitigación CSV injection
