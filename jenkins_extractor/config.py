from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Config:
    url: str
    user: str
    token: str = field(repr=False)  # nunca se imprime
    lookback_days: int = 30
    max_builds_per_job: int = 500
    max_workers: int = 4
    timeout: int = 30
    verify: bool | str = True
    timezone: str = "America/Santiago"
    output_dir: str = "out"
    include_regex: str | None = None
    exclude_regex: str | None = None
    include_users: bool = False
    sanitize_csv: bool = True

    @classmethod
    def from_env(cls, **overrides) -> "Config":
        # JENKINS_API_URL tiene prioridad; JENKINS_URL lo inyecta Jenkins al correr como job.
        url = os.getenv("JENKINS_API_URL") or os.getenv("JENKINS_URL")
        user = os.getenv("JENKINS_API_USER")
        token = os.getenv("JENKINS_API_TOKEN")
        missing = [
            name
            for name, val in (
                ("JENKINS_API_URL|JENKINS_URL", url),
                ("JENKINS_API_USER", user),
                ("JENKINS_API_TOKEN", token),
            )
            if not val
        ]
        if missing:
            raise ValueError("Faltan variables de entorno: " + ", ".join(missing))

        ca_bundle = os.getenv("JENKINS_CA_BUNDLE")
        verify: bool | str = ca_bundle or _bool(os.getenv("JENKINS_VERIFY_TLS"), True)

        values = dict(
            url=url.rstrip("/") + "/",
            user=user,
            token=token,
            lookback_days=int(os.getenv("LOOKBACK_DAYS", "30")),
            max_builds_per_job=int(os.getenv("MAX_BUILDS_PER_JOB", "500")),
            max_workers=int(os.getenv("MAX_WORKERS", "4")),
            timeout=int(os.getenv("HTTP_TIMEOUT", "30")),
            verify=verify,
            timezone=os.getenv("REPORT_TZ", "America/Santiago"),
            output_dir=os.getenv("OUTPUT_DIR", "out"),
            include_regex=os.getenv("JOB_INCLUDE_REGEX") or None,
            exclude_regex=os.getenv("JOB_EXCLUDE_REGEX") or None,
            include_users=_bool(os.getenv("EXTRACT_USERS"), False),
            sanitize_csv=_bool(os.getenv("CSV_SANITIZE"), True),
        )
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)
