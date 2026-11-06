from __future__ import annotations

import logging
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import __version__
from .config import Config

log = logging.getLogger(__name__)


class JenkinsClient:
    """Cliente mínimo de solo lectura (GET) para la API JSON de Jenkins."""

    def __init__(self, cfg: Config):
        self.base = cfg.url
        self.timeout = cfg.timeout

        session = requests.Session()
        session.auth = (cfg.user, cfg.token)  # API token => no requiere crumb
        session.verify = cfg.verify
        session.headers.update(
            {"User-Agent": f"jenkins-extractor/{__version__}", "Accept": "application/json"}
        )
        retry = Retry(
            total=4,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=max(cfg.max_workers * 2, 10))
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        self.session = session

    def get_json(self, path: str = "", tree: str | None = None) -> dict:
        """`path` relativo a la raíz y terminado en '/', p. ej. 'job/a/job/b/'."""
        url = urljoin(self.base, f"{path}api/json")
        params = {"tree": tree} if tree else None
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def server_info(self) -> dict:
        resp = self.session.get(
            urljoin(self.base, "api/json"), params={"tree": "mode"}, timeout=self.timeout
        )
        resp.raise_for_status()
        return {"version": resp.headers.get("X-Jenkins")}
