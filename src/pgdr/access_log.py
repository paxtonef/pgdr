"""Request log without request data (bloc 3A, point 5).

uvicorn's own access log writes each request's path and query string: in
PGDR they carry parcours and session identifiers. PGDR is therefore launched
with ``--no-access-log`` and logs through this middleware instead: one line
per request with the method, the matched route TEMPLATE (e.g.
``/api/v1/parcours/{pid}/selection``) or a fixed label, the status and the
duration -- never the path, the query, a header, a cookie, a body or a photo.

An exception escaping a route is logged as one fixed line naming its class
only (its message and traceback may carry request data) and answered with a
plain 500; nothing reaches uvicorn's error log.
"""
from __future__ import annotations

import logging
import sys
import time

logger = logging.getLogger("pgdr.access")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

NO_ROUTE = "(aucune route)"
_ERROR_BODY = b'{"detail":"Erreur interne."}'


def route_label(scope) -> str:
    """The matched route's template under its mount, a mount's fixed label, or NO_ROUTE."""
    route = scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str):
        return scope.get("root_path", "") + template
    endpoint = scope.get("endpoint")
    if endpoint is not None:
        return "montage:" + type(endpoint).__name__
    return NO_ROUTE


class AccessLogMiddleware:
    def __init__(self, app, logger: logging.Logger = logger):
        self.app = app
        self.logger = logger

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started, status = time.monotonic(), []

        async def send_and_note(message):
            if message["type"] == "http.response.start":
                status.append(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_and_note)
        except Exception as exc:  # noqa: BLE001 -- logged by class only, answered with a plain 500
            self.logger.error("%s %s exception %s", scope.get("method"), route_label(scope), type(exc).__name__)
            if not status:
                status.append(500)
                await send({"type": "http.response.start", "status": 500,
                            "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]})
                await send({"type": "http.response.body", "body": _ERROR_BODY})
        self.logger.info("%s %s %s %dms", scope.get("method"), route_label(scope), status[0] if status else "-",
                         int((time.monotonic() - started) * 1000))
