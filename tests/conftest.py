"""Jenkins falso en HTTP local para tests e2e del cliente y del CLI."""
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

NOW_MS = 1_762_300_800_000  # 2025-11-05T00:00:00Z
DAY = 86_400_000


def _b(n, result, days_ago, duration_ms=60_000, building=False, cause="hudson.model.Cause$UserIdCause"):
    return {
        "number": n,
        "result": result,
        "building": building,
        "timestamp": NOW_MS - days_ago * DAY,
        "duration": duration_ms,
        "builtOn": "",
        "actions": [{}, {"causes": [{"_class": cause, "userId": "alice"}]}],
    }


ROUTES = {
    "/api/json": {
        "jobs": [
            {"name": "freestyle-app", "_class": "hudson.model.FreeStyleProject", "color": "blue"},
            {"name": "team", "_class": "com.cloudbees.hudson.plugins.folder.Folder"},
        ]
    },
    "/job/team/api/json": {
        "jobs": [
            {"name": "=evil", "_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob", "color": "red"},
            {"name": "svc", "_class": "org.jenkinsci.plugins.workflow.multibranch.WorkflowMultiBranchProject"},
        ]
    },
    "/job/team/job/svc/api/json": {
        "jobs": [
            {"name": "main", "_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob", "color": "blue"},
            {"name": "feature%2Flogin", "_class": "org.jenkinsci.plugins.workflow.job.WorkflowJob", "color": "red"},
        ]
    },
    "/job/freestyle-app/api/json": {
        "allBuilds": [
            _b(4, None, 0, building=True),
            _b(3, "SUCCESS", 1, 30_000, cause="hudson.triggers.TimerTrigger$TimerTriggerCause"),
            _b(2, "FAILURE", 1, 90_000),
            _b(1, "SUCCESS", 400),  # fuera de ventana
        ]
    },
    "/job/team/job/%3Devil/api/json": {"allBuilds": [_b(1, "ABORTED", 2)]},
    "/job/team/job/svc/job/main/api/json": {
        "allBuilds": [_b(2, "SUCCESS", 0), _b(1, "UNSTABLE", 2, 120_000)]
    },
    # %252F: rama codificada dos veces como en Jenkins real
    "/job/team/job/svc/job/feature%252Flogin/api/json": None,  # 500 -> error controlado
}


class _Handler(BaseHTTPRequestHandler):
    requests_seen: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        type(self).requests_seen.append((parsed.path, parse_qs(parsed.query)))
        expected = "Basic " + base64.b64encode(b"svc:tok").decode()
        if self.headers.get("Authorization") != expected:
            self.send_response(401)
            self.end_headers()
            return
        if parsed.path not in ROUTES:
            self.send_response(404)
            self.end_headers()
            return
        body = ROUTES[parsed.path]
        if body is None:
            self.send_response(403)  # no reintentable
            self.end_headers()
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Jenkins", "2.479.1")
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture()
def fake_jenkins(monkeypatch):
    _Handler.requests_seen = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    monkeypatch.setenv("JENKINS_API_URL", url)
    monkeypatch.setenv("JENKINS_API_USER", "svc")
    monkeypatch.setenv("JENKINS_API_TOKEN", "tok")
    monkeypatch.setenv("REPORT_TZ", "America/Santiago")
    yield url, _Handler
    srv.shutdown()
