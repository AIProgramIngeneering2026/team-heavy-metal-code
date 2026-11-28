"""Bound actual request bytes before FastAPI reads or parses the JSON body."""

import json

from starlette.types import ASGIApp, Receive, Scope, Send

from .errors import error_response

MAX_BODY_BYTES = 65536


def reject_nonfinite_number(value):
    raise ValueError("JSON numbers must be finite")


class RequestBodyMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST" or scope["path"] != "/jobs":
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                response = error_response(413, "payload_too_large", "Request body must not exceed 65536 bytes.", [
                    {"field": "request_body", "issue": "Maximum size is 65536 bytes."}
                ])
                await response(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        headers = {key.lower(): value for key, value in scope["headers"]}
        media_type = headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower()
        if media_type != b"application/json":
            response = error_response(415, "unsupported_media_type", "Content-Type must be application/json.", [
                {"field": "Content-Type", "issue": "Unsupported media type."}
            ])
            await response(scope, receive, send)
            return
        try:
            # Python's default decoder accepts NaN/Infinity, which are not JSON.
            json.loads(body, parse_constant=reject_nonfinite_number)
        except (ValueError, UnicodeDecodeError, RecursionError):
            response = error_response(400, "invalid_json", "Request body is not valid JSON.")
            await response(scope, receive, send)
            return
        delivered = False

        async def replay_body():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay_body, send)
