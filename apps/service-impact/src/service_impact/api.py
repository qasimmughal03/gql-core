"""A minimal read-only JSON API over :class:`ImpactAnalyzer`, using only the standard library.

    GET /health
    GET /components
    GET /impact/<component-id>          affected components, owners, evidence paths
    GET /teams/<component-id>           teams to notify if the component fails
    GET /dependents/<database-id>       stored readers and writers of a database
    GET /hotspots?min=3                 services calling at least N components (typed plan)
    GET /tier-owners?tier=1             owning team per service in a tier (typed plan)
"""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from urllib.parse import parse_qs, urlparse

from service_impact.analysis import ImpactAnalyzer, UnknownComponent, as_dict


def make_server(analyzer: ImpactAnalyzer, host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep test output quiet
            pass

        def _send(self, status: int, body) -> None:
            data = json.dumps(body, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            parts = [p for p in url.path.split("/") if p]
            query = parse_qs(url.query)
            try:
                if parts == ["health"]:
                    return self._send(200, {"status": "ok", "gql_core": version("gql-core")})
                if parts == ["components"]:
                    return self._send(200, analyzer.components())
                if len(parts) == 2 and parts[0] == "impact":
                    affected = analyzer.impact(parts[1])
                    return self._send(200, {"failed": parts[1], "affected": [as_dict(a) for a in affected],
                                            "unowned": analyzer.unowned_affected(parts[1])})
                if len(parts) == 2 and parts[0] == "teams":
                    return self._send(200, analyzer.teams_to_notify(parts[1]))
                if len(parts) == 2 and parts[0] == "dependents":
                    return self._send(200, analyzer.dependents_of_database(parts[1]))
                if parts == ["hotspots"]:
                    return self._send(200, analyzer.fan_out_hotspots(int(query.get("min", ["3"])[0])))
                if parts == ["tier-owners"]:
                    return self._send(200, analyzer.tier_owners(int(query.get("tier", ["1"])[0])))
                return self._send(HTTPStatus.NOT_FOUND, {"error": f"no route {url.path}"})
            except UnknownComponent as exc:
                return self._send(HTTPStatus.NOT_FOUND, {"error": f"unknown component {exc.args[0]}"})
            except ValueError as exc:
                return self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    return ThreadingHTTPServer((host, port), Handler)
