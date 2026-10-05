"""What a request goes through before the application reads its body.

A framework dependency runs after the body has been parsed: by then an anonymous
client has already made the server spool an upload of any size. These checks run
first, on the headers alone:

- an `/api` call needs a known key, when keys are configured;
- a request that changes something and names its origin must come from this server's
  own pages: a page of another site open in the reviewer's browser cannot post here;
- a body is refused at its declared size, and cut off at the limit when it declared
  none or lied.

Every response also gets the headers that keep a browser from guessing a content type
or showing the console inside another site's frame.
"""

import hmac
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from countersign.config import ApiKey, Settings
from countersign.obs.logging import get_logger

logger = get_logger(__name__)

_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# A reviewed invoice of several hundred lines is a few tens of kilobytes of JSON.
MAX_JSON_BYTES = 1024 * 1024
# Boundaries and part headers around the file of a multipart upload.
_MULTIPART_OVERHEAD = 64 * 1024
_UPLOAD = ("POST", "/api/documents")


@dataclass(frozen=True)
class Principal:
    name: str
    role: str


def authenticate(keys: list[ApiKey], presented: str | None) -> Principal | None:
    """Who a request is from. Without configured keys everyone is a local reviewer."""
    if not keys:
        return Principal("local", "reviewer")
    for candidate in keys:
        if presented and hmac.compare_digest(candidate.key.encode(), presented.encode()):
            return Principal(candidate.name, candidate.role)
    return None


class Guard:
    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self.keys = settings.parsed_api_keys()
        self.max_upload_bytes = settings.max_upload_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        is_api = scope["path"].startswith("/api/")
        status = 500

        async def send_with_headers(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
                # API answers hold invoice data and are not to be kept by a browser or a
                # proxy. The console's own files are revalidated on each load, so an
                # upgrade of the server is never served with the previous script.
                headers.setdefault("Cache-Control", "no-store" if is_api else "no-cache")
            await send(message)

        try:
            if is_api:
                limit = self._body_limit(scope)
                refusal = self._refusal(scope, limit)
                if refusal is not None:
                    await refusal(scope, receive, send_with_headers)
                    return
                receive = _capped(receive, limit)
            await self.app(scope, receive, send_with_headers)
        finally:
            if is_api:
                logger.info(
                    "request",
                    extra={
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status,
                        "ms": round((time.perf_counter() - started) * 1000, 1),
                    },
                )

    def _body_limit(self, scope: Scope) -> int:
        if (scope["method"], scope["path"]) == _UPLOAD:
            return self.max_upload_bytes + _MULTIPART_OVERHEAD
        return MAX_JSON_BYTES

    def _refusal(self, scope: Scope, limit: int) -> Response | None:
        headers = Headers(scope=scope)
        principal = authenticate(self.keys, headers.get("x-api-key"))
        if principal is None:
            return _refuse(401, "missing or unknown API key")
        scope.setdefault("state", {})["principal"] = principal

        if scope["method"] in _MUTATING:
            origin = headers.get("origin")
            if origin is not None and urlsplit(origin).netloc != headers.get("host", ""):
                return _refuse(403, "this request comes from another site")

        declared = headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            return _refuse(413, _too_large(limit))
        return None


def _capped(receive: Receive, limit: int) -> Receive:
    """`receive`, but a body that grows past `limit` ends the request with 413."""
    received = 0

    async def capped() -> Message:
        nonlocal received
        message = await receive()
        if message["type"] == "http.request":
            received += len(message.get("body", b""))
            if received > limit:
                raise HTTPException(status_code=413, detail=_too_large(limit))
        return message

    return capped


def _too_large(limit: int) -> str:
    return f"request body larger than {limit // 1024} KB"


def _refuse(status: int, detail: str) -> Response:
    return JSONResponse({"detail": detail}, status_code=status)
