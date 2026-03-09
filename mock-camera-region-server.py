#!/usr/bin/env python3

"""
Mock Camera Server (Tornado)

Endpoints:
- POST /api/v1/captures
- GET  /api/v1/captures/*
- GET  /api/v1/images/full
- GET  /api/v1/regions
- PUT  /api/v1/regions  (echo regions back; requires Content-Type: application/json)
- GET  /index.html (serves PAGE verbatim, Content-Type: text/html)
- anything else -> 404 problem+json

Usage:
  ./mock_camera_server.py [--host 127.0.0.1] [--port 8080] PAGE FILE
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import tornado.escape
import tornado.ioloop
import tornado.web

CAPTURE_ID = "1772819158.2888863-8f3b2c"
CAPTURE_TIMESTAMP = 1772819158.2888863

POST_CAPTURES_BODY = (
    "{\n"
    f'"capture_id": "{CAPTURE_ID}",\n'
    f'"timestamp": {CAPTURE_TIMESTAMP},\n'
    '"status": "ready"\n'
    "}\n"
)

GET_CAPTURE_STATUS_BODY = (
    "{\n"
    f'    "capture_id": "{CAPTURE_ID}",\n'
    f'    "timestamp": {CAPTURE_TIMESTAMP},\n'
    '    "status": "ready",\n'
    '    "assets": {\n'
    f'        "full_jpeg": "/api/v1/images/full?capture_id={CAPTURE_ID}"\n'
    "    }\n"
    "}\n"
)

GET_REGIONS_BODY = "{\n" '    "version": 1,\n' '    "regions": []\n' "}\n"

PROBLEM_400_BODY = (
    "{\n"
    '    "type": "about:blank",\n'
    '    "title": "Bad Request",\n'
    '    "status": 400\n'
    "}\n"
)

PROBLEM_404_BODY = (
    "{\n"
    '    "type": "about:blank",\n'
    '    "title": "Not Found",\n'
    '    "status": 404\n'
    "}\n"
)


class BaseHandler(tornado.web.RequestHandler):
    def write_json(
        self, status: int, body: str, content_type: str = "application/json"
    ) -> None:
        self.set_status(status)
        self.set_header("Content-Type", content_type)
        self.write(body)

    def write_problem(self, status: int, body: str) -> None:
        self.write_json(
            status=status, body=body, content_type="application/problem+json"
        )


class CapturesHandler(BaseHandler):
    def post(self) -> None:
        self.set_status(201)
        self.set_header("Location", f"/api/v1/captures/{CAPTURE_ID}")
        self.set_header("Content-Type", "application/json")
        self.write(POST_CAPTURES_BODY)


class CaptureStatusWildcardHandler(BaseHandler):
    def get(self, _ignored: str) -> None:
        self.write_json(
            status=200, body=GET_CAPTURE_STATUS_BODY, content_type="application/json"
        )


class FullImageHandler(BaseHandler):
    def initialize(self, jpeg_bytes: bytes) -> None:
        self._jpeg_bytes = jpeg_bytes

    def get(self) -> None:
        self.set_status(200)
        self.set_header("Content-Type", "image/jpeg")
        self.set_header("X-Capture-Id", CAPTURE_ID)
        self.set_header("X-Capture-Timestamp", str(CAPTURE_TIMESTAMP))
        self.write(self._jpeg_bytes)


class IndexHtmlHandler(BaseHandler):
    def initialize(self, page_bytes: bytes) -> None:
        self._page_bytes = page_bytes

    def get(self) -> None:
        self.set_status(200)
        self.set_header("Content-Type", "text/html")
        self.write(self._page_bytes)


class RegionsHandler(BaseHandler):
    def get(self) -> None:
        self.write_json(
            status=200, body=GET_REGIONS_BODY, content_type="application/json"
        )

    def put(self) -> None:
        # Require JSON content-type (allow charset parameter).
        ct = self.request.headers.get("Content-Type", "")
        if not ct.lower().startswith("application/json"):
            self.write_problem(status=400, body=PROBLEM_400_BODY)
            return

        try:
            payload = tornado.escape.json_decode(self.request.body or b"")
        except Exception:
            self.write_problem(status=400, body=PROBLEM_400_BODY)
            return

        if (
            not isinstance(payload, dict)
            or "regions" not in payload
            or not isinstance(payload["regions"], list)
        ):
            self.write_problem(status=400, body=PROBLEM_400_BODY)
            return

        resp_obj = {"version": 1, "regions": payload["regions"]}
        body = json.dumps(resp_obj, indent=2) + "\n"
        self.write_json(status=200, body=body, content_type="application/json")


class NotFoundHandler(BaseHandler):
    def prepare(self) -> None:
        self.write_problem(status=404, body=PROBLEM_404_BODY)
        self.finish()


def load_bytes(path: str, label: str) -> bytes:
    if not os.path.isfile(path):
        print(
            f"error: {label} not found or not a regular file: {path}", file=sys.stderr
        )
        raise SystemExit(2)
    with open(path, "rb") as f:
        return f.read()


def load_jpeg_bytes(path: str) -> bytes:
    data = load_bytes(path, "FILE")
    if len(data) < 4 or not (data[0:2] == b"\xff\xd8" and data[-2:] == b"\xff\xd9"):
        print(
            f"warning: {path!r} does not look like a standard JPEG (FFD8...FFD9)",
            file=sys.stderr,
        )
    return data


def make_app(page_bytes: bytes, jpeg_bytes: bytes) -> tornado.web.Application:
    return tornado.web.Application(
        [
            (r"/api/v1/captures", CapturesHandler),
            (r"/api/v1/captures/(.*)", CaptureStatusWildcardHandler),
            (r"/api/v1/images/full", FullImageHandler, {"jpeg_bytes": jpeg_bytes}),
            (r"/api/v1/regions", RegionsHandler),
            (r"/index\.html", IndexHtmlHandler, {"page_bytes": page_bytes}),
        ],
        default_handler_class=NotFoundHandler,
        autoreload=False,
        debug=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Mock Camera Server")
    parser.add_argument(
        "--host", default="127.0.0.1", help='Bind host (default "127.0.0.1")'
    )
    parser.add_argument(
        "--port", default=8080, type=int, help="Bind port (default 8080)"
    )
    parser.add_argument(
        "PAGE", help="Path to an HTML file served verbatim at /index.html"
    )
    parser.add_argument(
        "FILE", help="Path to a JPEG file served at /api/v1/images/full"
    )
    args = parser.parse_args()

    page_bytes = load_bytes(args.PAGE, "PAGE")
    jpeg_bytes = load_jpeg_bytes(args.FILE)

    app = make_app(page_bytes=page_bytes, jpeg_bytes=jpeg_bytes)
    app.listen(args.port, address=args.host)

    print(f"Listening on http://{args.host}:{args.port}")
    tornado.ioloop.IOLoop.current().start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
