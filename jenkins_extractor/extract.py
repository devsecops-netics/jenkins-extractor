from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import quote, unquote
from zoneinfo import ZoneInfo

from .client import JenkinsClient
from .config import Config

log = logging.getLogger(__name__)

FOLDER_CLASS_HINTS = ("Folder", "MultiBranchProject", "OrganizationFolder")
JOB_TREE = "jobs[name,_class,color,buildable]"
BUILD_FIELDS = "number,result,building,timestamp,duration,builtOn,actions[causes[_class,userId]]"

CAUSE_MAP = {
    "hudson.model.Cause$UserIdCause": "user",
    "hudson.triggers.TimerTrigger$TimerTriggerCause": "timer",
    "hudson.triggers.SCMTrigger$SCMTriggerCause": "scm",
    "jenkins.branch.BranchEventCause": "scm",
    "jenkins.branch.BranchIndexingCause": "branch-indexing",
    "hudson.model.Cause$UpstreamCause": "upstream",
    "hudson.model.Cause$RemoteCause": "remote",
    "org.jenkinsci.plugins.workflow.cps.replay.ReplayCause": "replay",
    "com.cloudbees.jenkins.GitHubPushCause": "scm",
    "com.dabsquared.gitlabjenkins.cause.GitLabWebHookCause": "scm",
}


@dataclass
class Job:
    full_name: str
    name: str
    folder: str
    job_class: str
    job_type: str
    branch: str
    color: str
    buildable: bool | None
    url: str


@dataclass
class Build:
    job_full_name: str
    folder: str
    branch: str
    job_type: str
    number: int
    result: str
    building: bool
    started_at_utc: str
    started_date: str  # fecha local (REPORT_TZ) para agrupar por día
    timestamp_ms: int
    duration_s: float
    built_on: str
    trigger: str
    trigger_user: str
    url: str


@dataclass
class ExtractionResult:
    jobs: list[Job] = field(default_factory=list)
    builds: list[Build] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


def job_path(full_name: str) -> str:
    # quote(safe="") es intencional: ramas multibranch ya vienen codificadas
    # ("feature%2Fx") y Jenkins las expone como job/feature%252Fx/.
    return "".join(f"job/{quote(part, safe='')}/" for part in full_name.split("/"))


def is_folder(job_class: str) -> bool:
    return any(hint in job_class for hint in FOLDER_CLASS_HINTS)


def classify_job_type(job_class: str, parent_class: str | None) -> str:
    if parent_class and "MultiBranchProject" in parent_class:
        return "multibranch-branch"
    if "WorkflowJob" in job_class:
        return "pipeline"
    if "FreeStyleProject" in job_class:
        return "freestyle"
    if "MatrixProject" in job_class:
        return "matrix"
    return job_class.rsplit(".", 1)[-1] or "unknown"


def discover_jobs(
    client: JenkinsClient,
    prefix: str = "",
    parent_class: str | None = None,
    depth: int = 0,
    max_depth: int = 10,
) -> Iterator[Job]:
    if depth > max_depth:
        log.warning("Profundidad máxima alcanzada en %s", prefix)
        return
    path = job_path(prefix) if prefix else ""
    data = client.get_json(path, tree=JOB_TREE)
    for item in data.get("jobs") or []:
        name = item["name"]
        cls = item.get("_class", "")
        full = f"{prefix}/{name}" if prefix else name
        if is_folder(cls):
            yield from discover_jobs(client, full, cls, depth + 1, max_depth)
            continue
        job_type = classify_job_type(cls, parent_class)
        yield Job(
            full_name=full,
            name=name,
            folder=prefix,
            job_class=cls,
            job_type=job_type,
            branch=unquote(name) if job_type == "multibranch-branch" else "",
            color=item.get("color") or "",
            buildable=item.get("buildable"),
            url=client.base + job_path(full),
        )


def _trigger(actions: list | None, include_users: bool) -> tuple[str, str]:
    for action in actions or []:
        for cause in (action or {}).get("causes") or []:
            cls = cause.get("_class", "")
            kind = CAUSE_MAP.get(cls, cls.rsplit(".", 1)[-1] or "other")
            user = (cause.get("userId") or "") if include_users else ""
            return kind, user
    return "unknown", ""


def _result(raw: dict) -> str:
    if raw.get("building"):
        return "IN_PROGRESS"
    return raw.get("result") or "NOT_BUILT"


def extract_builds(
    client: JenkinsClient, job: Job, since_ms: int, cfg: Config, tz: ZoneInfo
) -> list[Build]:
    path = job_path(job.full_name)
    rng = f"{{0,{cfg.max_builds_per_job}}}"
    data = client.get_json(path, tree=f"allBuilds[{BUILD_FIELDS}]{rng}")
    raw_builds = data.get("allBuilds")
    if raw_builds is None:  # algunos tipos de job no exponen allBuilds
        data = client.get_json(path, tree=f"builds[{BUILD_FIELDS}]{rng}")
        raw_builds = data.get("builds") or []

    builds: list[Build] = []
    for raw in raw_builds:
        ts = int(raw.get("timestamp") or 0)
        if ts < since_ms:
            continue
        started = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        trigger, user = _trigger(raw.get("actions"), cfg.include_users)
        builds.append(
            Build(
                job_full_name=job.full_name,
                folder=job.folder,
                branch=job.branch,
                job_type=job.job_type,
                number=int(raw["number"]),
                result=_result(raw),
                building=bool(raw.get("building")),
                started_at_utc=started.isoformat(timespec="seconds"),
                started_date=started.astimezone(tz).date().isoformat(),
                timestamp_ms=ts,
                duration_s=round((raw.get("duration") or 0) / 1000, 3),
                built_on=raw.get("builtOn") or "built-in",
                trigger=trigger,
                trigger_user=user,
                url=f"{job.url}{raw['number']}/",
            )
        )
    return builds


def _filter_jobs(jobs: list[Job], cfg: Config) -> list[Job]:
    inc = re.compile(cfg.include_regex) if cfg.include_regex else None
    exc = re.compile(cfg.exclude_regex) if cfg.exclude_regex else None
    return [
        j
        for j in jobs
        if (inc is None or inc.search(j.full_name)) and not (exc and exc.search(j.full_name))
    ]


def extract_all(client: JenkinsClient, cfg: Config, now: datetime | None = None) -> ExtractionResult:
    now = now or datetime.now(timezone.utc)
    since_ms = int(now.timestamp() * 1000) - cfg.lookback_days * 86_400_000
    tz = ZoneInfo(cfg.timezone)

    result = ExtractionResult()
    result.jobs = _filter_jobs(list(discover_jobs(client)), cfg)
    log.info("Jobs descubiertos: %d", len(result.jobs))

    with ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
        futures = {pool.submit(extract_builds, client, j, since_ms, cfg, tz): j for j in result.jobs}
        for fut in as_completed(futures):
            job = futures[fut]
            try:
                result.builds.extend(fut.result())
            except Exception as exc:  # un job roto no debe tumbar la extracción
                log.warning("Error extrayendo %s: %s", job.full_name, exc)
                result.errors.append({"job": job.full_name, "error": str(exc)})

    result.builds.sort(key=lambda b: (b.job_full_name, b.number))
    return result
