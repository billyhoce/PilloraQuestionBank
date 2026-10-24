"""Request-id middleware: ``X-Request-ID`` is taken from the request or generated, put on every
log record of the request and echoed on the response (pure ASGI, so contextvars reach the route)."""

import uuid

from starlette.datastructures import Headers, MutableHeaders

from app.log_context import log_context

HEADER = "X-Request-ID"
MAX_LENGTH = 128


class RequestIdMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = Headers(scope=scope).get(HEADER, "").strip()
        # Printable ASCII only, bounded: the value is echoed in a header and written to logs.
        if not supplied or len(supplied) > MAX_LENGTH or not supplied.isascii() or not supplied.isprintable():
            supplied = uuid.uuid4().hex
        request_id = supplied

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[HEADER] = request_id
            await send(message)

        with log_context(request_id=request_id):
            await self.app(scope, receive, send_with_id)
