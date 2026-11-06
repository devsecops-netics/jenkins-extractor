from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import asdict, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import __version__, metrics
from .client import JenkinsClient
from .config import Config
from .extract import Build, Job, extract_all
from .writers import write_csv, write_json

log = logging.getLogger("jenkins_extractor")

JOB_FIELDS = [f.name for f in fields(Job)]
BUILD_FIELDS = [f.name for f in fields(Build)]


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="jenkins_extractor", description="Extrae builds de Jenkins a CSV/JSON")
    p.add_argument("--lookback-days", type=int, help="Ventana de días (default: LOOKBACK_DAYS o 30)")
    p.add_argument("--output", help="Directorio de salida (default: OUTPUT_DIR o ./out)")
    p.add_argument("--include", help="Regex sobre fullName de jobs a incluir")
    p.add_argument("--exclude", help="Regex sobre fullName de jobs a excluir")
    p.add_argument("--strict", action="store_true", help="Exit 1 si algún job falló")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        cfg = Config.from_env(
            lookback_days=args.lookback_days,
            output_dir=args.output,
            include_regex=args.include,
            exclude_regex=args.exclude,
        )
    except ValueError as exc:
        log.error("%s", exc)
        return 2

    if cfg.verify is False:
        log.warning("Verificación TLS deshabilitada (JENKINS_VERIFY_TLS=false)")

    now = datetime.now(timezone.utc)
    client = JenkinsClient(cfg)
    info = client.server_info()
    log.info("Jenkins %s en %s | ventana %d días", info.get("version"), cfg.url, cfg.lookback_days)

    result = extract_all(client, cfg, now=now)

    out = Path(cfg.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    s = cfg.sanitize_csv
    write_csv(out / "jobs.csv", (asdict(j) for j in result.jobs), JOB_FIELDS, s)
    write_csv(out / "builds.csv", (asdict(b) for b in result.builds), BUILD_FIELDS, s)
    write_csv(out / "success_rate_by_job.csv", metrics.summary_by_job(result.builds), metrics.SUMMARY_FIELDS, s)
    write_csv(out / "success_rate_daily_by_job.csv", metrics.daily_by_job(result.builds), metrics.DAILY_JOB_FIELDS, s)
    write_csv(out / "success_rate_daily.csv", metrics.daily_global(result.builds), metrics.DAILY_GLOBAL_FIELDS, s)
    write_json(
        out / "metadata.json",
        {
            "extractor_version": __version__,
            "extracted_at_utc": now.isoformat(timespec="seconds"),
            "jenkins_url": cfg.url,
            "jenkins_version": info.get("version"),
            "lookback_days": cfg.lookback_days,
            "since_utc": (now - timedelta(days=cfg.lookback_days)).isoformat(timespec="seconds"),
            "report_timezone": cfg.timezone,
            "jobs": len(result.jobs),
            "builds": len(result.builds),
            "success_rate_definition": metrics.SUCCESS_RATE_DEFINITION,
            "errors": result.errors,
        },
    )
    log.info("OK: %d jobs, %d builds, %d errores -> %s", len(result.jobs), len(result.builds), len(result.errors), out.resolve())
    return 1 if (args.strict and result.errors) else 0


if __name__ == "__main__":
    sys.exit(main())
