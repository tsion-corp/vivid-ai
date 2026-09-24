"""One error shape for the whole REST surface.

The websocket has always carried stable `code` strings (`rate_limited`,
`llm_error`, `busy`); REST carried bare FastAPI `{"detail": "..."}` strings,
which an SDK cannot branch on. Partner code has to decide what to retry —
a full browser tier is worth retrying, a blocked URL never is — and that
decision needs a code, not prose.

Responses carry BOTH the envelope and the legacy `detail` key:

    {"error": {"code": "not_found", "message": "Chat not found",
               "request_id": "req_..."},
     "detail": "Chat not found"}

`detail` is deprecated and exists only so the current frontend, which reads it
directly (vivid-frontend/lib/backend/client.ts), keeps showing real error
messages instead of "Request failed (404)". Drop it once the frontend moves to
the SDK.
"""
import logging
import uuid
from typing import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("vivid.errors")

REQUEST_ID_HEADER = "X-Request-Id"

#: Status -> code, for the many places that still raise a bare HTTPException.
#: A route wanting something more precise raises APIError with its own code.
_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "invalid_request",
    429: "rate_limited",
    500: "internal_error",
    502: "upstream_error",
    503: "service_unavailable",
    504: "upstream_timeout",
}


class APIError(Exception):
    """An error with a stable machine-readable code.

    Raise this instead of HTTPException anywhere a caller might reasonably
    branch on what went wrong.
    """

    def __init__(self, status: int, code: str, message: str,
                 headers: dict | None = None, details: dict | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}
        #: Machine-readable context for the client (limits, reset times).
        self.details = details


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or ""


def _payload(code: str, message: str, rid: str, details: dict | None = None) -> dict:
    error = {"code": code, "message": message, "request_id": rid}
    if details:
        error["details"] = details
    return {"error": error, "detail": message}  # deprecated mirror; see module docstring


def _response(status: int, code: str, message: str, rid: str,
              headers: dict | None = None, details: dict | None = None) -> JSONResponse:
    merged = {REQUEST_ID_HEADER: rid, **(headers or {})}
    return JSONResponse(status_code=status, content=_payload(code, message, rid, details),
                        headers=merged)


def install(app: FastAPI) -> None:
    """Register the middleware and handlers. Called once from main."""

    @app.middleware("http")
    async def _request_id_middleware(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Honour an inbound id so a request can be traced across services, but
        # cap it: this value is echoed into responses and logs.
        inbound = (request.headers.get(REQUEST_ID_HEADER) or "").strip()[:64]
        rid = inbound or f"req_{uuid.uuid4().hex[:20]}"
        request.state.request_id = rid
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = rid
        return response

    @app.exception_handler(APIError)
    async def _api_error(request: Request, exc: APIError) -> JSONResponse:
        return _response(exc.status, exc.code, exc.message,
                         request_id(request), exc.headers, exc.details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request,
                          exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        message = detail if isinstance(detail, str) else str(detail)
        code = _STATUS_CODES.get(exc.status_code, "error")
        headers = dict(getattr(exc, "headers", None) or {})
        return _response(exc.status_code, code, message, request_id(request),
                         headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request,
                                exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default body is a list of per-field dicts. Keep the detail
        # of it — a partner debugging a 422 needs to know which field — but
        # under the same envelope as everything else.
        first = (exc.errors() or [{}])[0]
        loc = " -> ".join(str(p) for p in (first.get("loc") or []) if p != "body")
        message = first.get("msg") or "invalid request"
        rid = request_id(request)
        body = _payload("invalid_request",
                        f"{loc}: {message}" if loc else message, rid)
        body["error"]["fields"] = [
            {"field": " -> ".join(str(p) for p in (e.get("loc") or [])
                                  if p != "body"),
             "message": e.get("msg", "")}
            for e in exc.errors()[:10]]
        return JSONResponse(status_code=422, content=body,
                            headers={REQUEST_ID_HEADER: rid})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        rid = request_id(request)
        # Log the whole thing; return only the id. An unhandled exception's
        # message can carry connection strings and internal hostnames, and
        # this surface is now reachable by partners.
        log.exception("unhandled error on %s %s (request_id=%s)",
                      request.method, request.url.path, rid)
        return _response(500, "internal_error",
                         "an unexpected error occurred; quote the request_id "
                         "when reporting it", rid)


__all__ = ["APIError", "HTTPException", "install", "request_id",
           "REQUEST_ID_HEADER"]
