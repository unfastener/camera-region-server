#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image
import tornado.ioloop
import tornado.web


JSON_CT = "application/json; charset=utf-8"
PROBLEM_CT = "application/problem+json"
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ProblemError(Exception):
    def __init__(
        self,
        status: int,
        title: str,
        detail: str,
        type_: str = "about:blank",
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.title = title
        self.detail = detail
        self.type = type_


def parse_bool_arg(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ProblemError(
        400,
        "Invalid parameters",
        f"Invalid boolean value: {value!r}.",
        "https://example.invalid/problems/invalid-parameters",
    )


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def read_file_bytes(path: Path) -> bytes:
    with path.open("rb") as handle:
        return handle.read()


def json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2) + "\n"


@dataclass(frozen=True)
class Geometry:
    cx: float
    cy: float
    width: int
    height: int
    rotation_deg: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "cx": self.cx,
            "cy": self.cy,
            "width": self.width,
            "height": self.height,
            "rotation_deg": self.rotation_deg,
        }


@dataclass(frozen=True)
class Region:
    name: str
    description: str
    geometry: Geometry

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "geometry": self.geometry.to_dict(),
        }


@dataclass
class RegionConfig:
    version: int
    regions: list[Region]

    @property
    def etag(self) -> str:
        return f'"regions-v{self.version}"'

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "regions": [region.to_dict() for region in self.regions]}


@dataclass
class Capture:
    capture_id: str
    timestamp: float
    directory: Path
    regions: list[Region]
    full_path: Path
    region_paths: dict[int, Path] = field(default_factory=dict)
    region_errors: dict[int, ProblemError] = field(default_factory=dict)
    status: str = "processing"
    error_code: str | None = None
    message: str | None = None
    ready_event: asyncio.Event = field(default_factory=asyncio.Event)
    image_size: tuple[int, int] | None = None

    def status_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "capture_id": self.capture_id,
            "timestamp": self.timestamp,
            "status": self.status,
        }
        if self.status == "ready":
            payload["assets"] = {
                "full_jpeg": f"api/v1/images/full?capture_id={self.capture_id}",
            }
        if self.status == "failed":
            payload["error_code"] = self.error_code or "capture_failed"
            payload["message"] = self.message or "Capture failed."
        return payload


class RegionStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()
        self._config = self._load()

    def _load(self) -> RegionConfig:
        if not self._path.exists():
            return RegionConfig(version=0, regions=[])

        with self._path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        if not isinstance(payload, dict):
            raise ValueError(f"Invalid region file: {self._path}")

        version = payload.get("version")
        regions_payload = payload.get("regions", [])
        if not isinstance(regions_payload, list):
            raise ValueError(f"Invalid region list in {self._path}")

        regions = validate_regions_payload({"regions": regions_payload})
        if isinstance(version, int) and version >= 0:
            loaded_version = version
        else:
            loaded_version = 1 if regions else 0
        return RegionConfig(version=loaded_version, regions=regions)

    async def get(self) -> RegionConfig:
        async with self._lock:
            return RegionConfig(self._config.version, list(self._config.regions))

    async def replace(self, payload: dict[str, Any], if_match: str | None) -> RegionConfig:
        regions = validate_regions_payload(payload)
        async with self._lock:
            if if_match is not None and if_match != self._config.etag:
                raise ProblemError(
                    412,
                    "Precondition failed",
                    "If-Match does not match the current regions ETag.",
                    "https://example.invalid/problems/precondition-failed",
                )
            next_config = RegionConfig(version=self._config.version + 1, regions=regions)
            atomic_write_json(self._path, next_config.to_dict())
            self._config = next_config
            return RegionConfig(next_config.version, list(next_config.regions))


def _require_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProblemError(
            400,
            "Invalid parameters",
            f"Field {field_name!r} must be a number.",
            "https://example.invalid/problems/invalid-parameters",
        )
    return float(value)


def _require_positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProblemError(
            400,
            "Invalid parameters",
            f"Field {field_name!r} must be an integer greater than 0.",
            "https://example.invalid/problems/invalid-parameters",
        )
    return value


def validate_regions_payload(payload: dict[str, Any]) -> list[Region]:
    if not isinstance(payload, dict) or not isinstance(payload.get("regions"), list):
        raise ProblemError(
            400,
            "Invalid parameters",
            "JSON body must contain a 'regions' array.",
            "https://example.invalid/problems/invalid-parameters",
        )

    validated: list[Region] = []
    names: set[str] = set()
    for index, region_payload in enumerate(payload["regions"]):
        if not isinstance(region_payload, dict):
            raise ProblemError(
                400,
                "Invalid parameters",
                f"Region at index {index} must be an object.",
                "https://example.invalid/problems/invalid-parameters",
            )
        name = region_payload.get("name")
        description = region_payload.get("description", "")
        geometry_payload = region_payload.get("geometry")

        if not isinstance(name, str) or not IDENTIFIER_RE.fullmatch(name):
            raise ProblemError(
                400,
                "Invalid parameters",
                f"Region at index {index} has an invalid name.",
                "https://example.invalid/problems/invalid-parameters",
            )
        if name in names:
            raise ProblemError(
                400,
                "Invalid parameters",
                f"Duplicate region name: {name!r}.",
                "https://example.invalid/problems/invalid-parameters",
            )
        names.add(name)

        if description is None:
            description = ""
        if not isinstance(description, str) or len(description) > 256:
            raise ProblemError(
                400,
                "Invalid parameters",
                f"Region {name!r} has an invalid description.",
                "https://example.invalid/problems/invalid-parameters",
            )
        if not isinstance(geometry_payload, dict):
            raise ProblemError(
                400,
                "Invalid parameters",
                f"Region {name!r} must contain a geometry object.",
                "https://example.invalid/problems/invalid-parameters",
            )

        geometry = Geometry(
            cx=_require_number(geometry_payload.get("cx"), "cx"),
            cy=_require_number(geometry_payload.get("cy"), "cy"),
            width=_require_positive_int(geometry_payload.get("width"), "width"),
            height=_require_positive_int(geometry_payload.get("height"), "height"),
            rotation_deg=_require_number(geometry_payload.get("rotation_deg"), "rotation_deg"),
        )
        validated.append(Region(name=name, description=description, geometry=geometry))
    return validated


def region_affine_coefficients(region: Region) -> tuple[float, float, float, float, float, float]:
    geometry = region.geometry
    # Pillow's affine transform maps output pixels back into source-image
    # coordinates, so the user-facing rotation sign needs to be inverted here.
    theta = math.radians(-geometry.rotation_deg)
    cos_theta = math.cos(theta)
    sin_theta = math.sin(theta)
    half_w = (geometry.width - 1) / 2.0
    half_h = (geometry.height - 1) / 2.0
    return (
        cos_theta,
        -sin_theta,
        geometry.cx - cos_theta * half_w + sin_theta * half_h,
        sin_theta,
        cos_theta,
        geometry.cy - sin_theta * half_w - cos_theta * half_h,
    )


def ensure_region_in_bounds(region: Region, image_size: tuple[int, int]) -> None:
    src_w, src_h = image_size
    a, b, c, d, e, f = region_affine_coefficients(region)
    geometry = region.geometry
    corners = (
        (0, 0),
        (geometry.width - 1, 0),
        (0, geometry.height - 1),
        (geometry.width - 1, geometry.height - 1),
    )
    for u, v in corners:
        x = a * u + b * v + c
        y = d * u + e * v + f
        if not (0.0 <= x <= src_w - 1 and 0.0 <= y <= src_h - 1):
            raise ProblemError(
                422,
                "Region out of bounds",
                f"Region {region.name!r} samples outside the source image bounds.",
                "https://example.invalid/problems/region-out-of-bounds",
            )


def render_region(image: Image.Image, region: Region) -> Image.Image:
    ensure_region_in_bounds(region, image.size)
    output_size = (region.geometry.width, region.geometry.height)
    return image.transform(
        output_size,
        Image.Transform.AFFINE,
        region_affine_coefficients(region),
        resample=Image.Resampling.BICUBIC,
    )


class CaptureManager:
    def __init__(
        self,
        region_store: RegionStore,
        capture_root: Path,
        take_picture_cmd: str,
        wait_timeout: float,
    ) -> None:
        self._region_store = region_store
        self._capture_root = capture_root
        self._take_picture_cmd = take_picture_cmd
        self._wait_timeout = wait_timeout
        self._captures: dict[str, Capture] = {}
        self._latest_capture_id: str | None = None
        self._in_progress_capture_id: str | None = None
        self._lock = asyncio.Lock()
        self._capture_root.mkdir(parents=True, exist_ok=True)

    async def start_capture(self) -> Capture:
        async with self._lock:
            if self._in_progress_capture_id is not None:
                return self._captures[self._in_progress_capture_id]
            capture = await self._create_capture_locked()
            self._in_progress_capture_id = capture.capture_id
            self._latest_capture_id = capture.capture_id
            asyncio.create_task(self._run_capture(capture))
            return capture

    async def _create_capture_locked(self) -> Capture:
        timestamp = time.time()
        capture_id = f"{timestamp:.6f}-{uuid.uuid4().hex[:6]}"
        directory = self._capture_root / capture_id
        directory.mkdir(parents=True, exist_ok=False)
        regions = (await self._region_store.get()).regions
        capture = Capture(
            capture_id=capture_id,
            timestamp=timestamp,
            directory=directory,
            regions=regions,
            full_path=directory / "full.jpg",
        )
        self._captures[capture_id] = capture
        return capture

    async def _run_capture(self, capture: Capture) -> None:
        try:
            await asyncio.to_thread(self._take_picture, capture.full_path)
            await asyncio.to_thread(self._derive_regions, capture)
            capture.status = "ready"
        except ProblemError as exc:
            capture.status = "failed"
            capture.error_code = "region_out_of_bounds" if exc.status == 422 else "capture_error"
            capture.message = exc.detail
        except Exception as exc:
            capture.status = "failed"
            capture.error_code = "camera_error"
            capture.message = str(exc)
        finally:
            capture.ready_event.set()
            async with self._lock:
                if self._in_progress_capture_id == capture.capture_id:
                    self._in_progress_capture_id = None

    def _take_picture(self, output_path: Path) -> None:
        result = subprocess.run(
            [self._take_picture_cmd, str(output_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise ProblemError(
                503,
                "Service unavailable",
                f"{self._take_picture_cmd} failed with exit code {result.returncode}.",
                "https://example.invalid/problems/camera-unavailable",
            )
        if not output_path.is_file():
            raise ProblemError(
                503,
                "Service unavailable",
                f"{self._take_picture_cmd} did not create the output JPEG.",
                "https://example.invalid/problems/camera-unavailable",
            )

    def _derive_regions(self, capture: Capture) -> None:
        with Image.open(capture.full_path) as image:
            source = image.convert("RGB")
            capture.image_size = source.size
            for index, region in enumerate(capture.regions):
                try:
                    rendered = render_region(source, region)
                except ProblemError as exc:
                    capture.region_errors[index] = exc
                    continue
                region_path = capture.directory / f"region-{index:04d}-{region.name}.jpg"
                rendered.save(region_path, format="JPEG", quality=95)
                capture.region_paths[index] = region_path

    async def get_capture(self, capture_id: str) -> Capture | None:
        async with self._lock:
            return self._captures.get(capture_id)

    async def get_latest_capture(self) -> Capture | None:
        async with self._lock:
            if self._latest_capture_id is None:
                return None
            return self._captures.get(self._latest_capture_id)

    async def resolve_capture(self, capture_id: str | None, new_capture: bool) -> Capture:
        if capture_id is not None:
            capture = await self.get_capture(capture_id)
            if capture is None:
                raise ProblemError(
                    404,
                    "Not found",
                    f"Unknown capture_id: {capture_id}.",
                    "https://example.invalid/problems/not-found",
                )
            return capture

        if new_capture:
            return await self.start_capture()
        latest = await self.get_latest_capture()
        if latest is not None:
            return latest
        raise ProblemError(
            409,
            "Conflict",
            "No cached captures are available.",
            "https://example.invalid/problems/no-cached-captures",
        )

    async def wait_for_ready(self, capture: Capture) -> None:
        if capture.status != "processing":
            return
        try:
            await asyncio.wait_for(capture.ready_event.wait(), timeout=self._wait_timeout)
        except TimeoutError as exc:
            raise ProblemError(
                504,
                "Gateway timeout",
                "Capture did not complete within the server wait timeout.",
                "https://example.invalid/problems/wait-timeout",
            ) from exc


class BaseHandler(tornado.web.RequestHandler):
    @property
    def state(self) -> "AppState":
        return self.application.settings["state"]

    def write_problem(self, status: int, title: str, detail: str, type_: str = "about:blank") -> None:
        self.set_status(status)
        self.set_header("Content-Type", PROBLEM_CT)
        self.write(
            json_dumps(
                {
                    "type": type_,
                    "title": title,
                    "status": status,
                    "detail": detail,
                    "instance": self.request.path,
                }
            )
        )

    def write_json(self, status: int, payload: dict[str, Any]) -> None:
        self.set_status(status)
        self.set_header("Content-Type", JSON_CT)
        self.write(json_dumps(payload))

    def write_capture_status(self, status: int, capture: Capture) -> None:
        self.set_status(status)
        self.set_header("Content-Type", JSON_CT)
        self.set_header("Location", f"api/v1/captures/{capture.capture_id}")
        if status == 202:
            self.set_header("Retry-After", "1")
        self.write(json_dumps(capture.status_payload()))

    def write_image_headers(self, capture: Capture, region_index: int | None = None, region_name: str | None = None) -> None:
        self.set_header("Content-Type", "image/jpeg")
        self.set_header("Cache-Control", "no-store")
        self.set_header("X-Capture-Id", capture.capture_id)
        self.set_header("X-Capture-Timestamp", f"{capture.timestamp:.6f}")
        if region_index is not None:
            self.set_header("X-Region-Index", str(region_index))
        if region_name is not None:
            self.set_header("X-Region-Name", region_name)

    def write_error(self, status_code: int, **kwargs: Any) -> None:
        if self._finished:
            return
        self.write_problem(status_code, "Not found" if status_code == 404 else "Error", self._reason)

    def require_json_body(self) -> dict[str, Any]:
        content_type = self.request.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            raise ProblemError(
                400,
                "Invalid parameters",
                "Content-Type must be application/json.",
                "https://example.invalid/problems/invalid-parameters",
            )
        try:
            payload = json.loads(self.request.body or b"{}")
        except json.JSONDecodeError as exc:
            raise ProblemError(
                400,
                "Invalid parameters",
                f"Invalid JSON body: {exc.msg}.",
                "https://example.invalid/problems/invalid-parameters",
            ) from exc
        if not isinstance(payload, dict):
            raise ProblemError(
                400,
                "Invalid parameters",
                "JSON body must be an object.",
                "https://example.invalid/problems/invalid-parameters",
            )
        return payload


class CapturesHandler(BaseHandler):
    async def post(self) -> None:
        try:
            capture = await self.state.capture_manager.start_capture()
            status = 202 if capture.status == "processing" else 201
            self.write_capture_status(status, capture)
        except ProblemError as exc:
            self.write_problem(exc.status, exc.title, exc.detail, exc.type)


class CaptureStatusHandler(BaseHandler):
    async def get(self, capture_id: str) -> None:
        capture = await self.state.capture_manager.get_capture(capture_id)
        if capture is None:
            self.write_problem(
                404,
                "Not found",
                f"Unknown capture_id: {capture_id}.",
                "https://example.invalid/problems/not-found",
            )
            return
        self.write_json(200, capture.status_payload())


class FullImageHandler(BaseHandler):
    async def get(self) -> None:
        try:
            capture_id = self.get_query_argument("capture_id", None)
            new_capture = parse_bool_arg(self.get_query_argument("new_capture", None), False)
            wait = parse_bool_arg(self.get_query_argument("wait", None), True)

            capture = await self.state.capture_manager.resolve_capture(capture_id, new_capture)
            if capture.status == "processing":
                if not wait:
                    self.write_capture_status(202, capture)
                    return
                await self.state.capture_manager.wait_for_ready(capture)
            if capture.status == "failed":
                raise ProblemError(
                    503,
                    "Service unavailable",
                    capture.message or "Capture failed.",
                    "https://example.invalid/problems/camera-unavailable",
                )
            self.set_status(200)
            self.write_image_headers(capture)
            self.write(read_file_bytes(capture.full_path))
        except ProblemError as exc:
            self.write_problem(exc.status, exc.title, exc.detail, exc.type)


class RegionImageHandler(BaseHandler):
    async def get(self) -> None:
        try:
            raw_index = self.get_query_argument("index", None)
            raw_name = self.get_query_argument("name", None)
            if (raw_index is None) == (raw_name is None):
                raise ProblemError(
                    400,
                    "Invalid parameters",
                    "Exactly one of 'index' or 'name' must be provided.",
                    "https://example.invalid/problems/invalid-parameters",
                )

            capture_id = self.get_query_argument("capture_id", None)
            wait = parse_bool_arg(self.get_query_argument("wait", None), True)
            source = self.get_query_argument("source", "auto")
            if source not in {"auto", "on_demand"}:
                raise ProblemError(
                    400,
                    "Invalid parameters",
                    "Parameter 'source' must be 'auto' or 'on_demand'.",
                    "https://example.invalid/problems/invalid-parameters",
                )

            capture = await self.state.capture_manager.resolve_capture(capture_id, False)
            if capture.status == "processing":
                if not wait:
                    self.write_capture_status(202, capture)
                    return
                await self.state.capture_manager.wait_for_ready(capture)
            if capture.status == "failed":
                raise ProblemError(
                    503,
                    "Service unavailable",
                    capture.message or "Capture failed.",
                    "https://example.invalid/problems/camera-unavailable",
                )

            region_index, region = resolve_region_selector(capture.regions, raw_index, raw_name)
            region_error = capture.region_errors.get(region_index)
            if region_error is not None:
                raise region_error
            region_path = capture.region_paths.get(region_index)
            if region_path is None or not region_path.exists() or source == "on_demand":
                await asyncio.to_thread(self._render_on_demand, capture, region_index, region)
                region_path = capture.region_paths[region_index]

            self.set_status(200)
            self.write_image_headers(capture, region_index=region_index, region_name=region.name)
            self.write(read_file_bytes(region_path))
        except ProblemError as exc:
            self.write_problem(exc.status, exc.title, exc.detail, exc.type)

    def _render_on_demand(self, capture: Capture, region_index: int, region: Region) -> None:
        with Image.open(capture.full_path) as image:
            source = image.convert("RGB")
            rendered = render_region(source, region)
            region_path = capture.directory / f"region-{region_index:04d}-{region.name}.jpg"
            rendered.save(region_path, format="JPEG", quality=95)
            capture.region_paths[region_index] = region_path


def resolve_region_selector(regions: list[Region], raw_index: str | None, raw_name: str | None) -> tuple[int, Region]:
    if raw_index is not None:
        try:
            region_index = int(raw_index)
        except ValueError as exc:
            raise ProblemError(
                400,
                "Invalid parameters",
                "Parameter 'index' must be an integer.",
                "https://example.invalid/problems/invalid-parameters",
            ) from exc
        if not 0 <= region_index < len(regions):
            raise ProblemError(
                404,
                "Not found",
                f"Region index {region_index} does not exist.",
                "https://example.invalid/problems/not-found",
            )
        return region_index, regions[region_index]

    assert raw_name is not None
    for idx, region in enumerate(regions):
        if region.name == raw_name:
            return idx, region
    raise ProblemError(
        404,
        "Not found",
        f"Region name {raw_name!r} does not exist.",
        "https://example.invalid/problems/not-found",
    )


class RegionsHandler(BaseHandler):
    async def get(self) -> None:
        config = await self.state.region_store.get()
        self.set_header("ETag", config.etag)
        self.set_header("Cache-Control", "no-cache")
        self.write_json(200, config.to_dict())

    async def put(self) -> None:
        try:
            payload = self.require_json_body()
            updated = await self.state.region_store.replace(payload, self.request.headers.get("If-Match"))
            self.set_header("ETag", updated.etag)
            self.set_header("Cache-Control", "no-cache")
            self.write_json(200, updated.to_dict())
        except ProblemError as exc:
            self.write_problem(exc.status, exc.title, exc.detail, exc.type)


class StaticRootHandler(BaseHandler):
    def get(self, requested_path: str) -> None:
        if self.state.static_dir is None:
            self.write_problem(
                404,
                "Not found",
                "No static file root is configured.",
                "https://example.invalid/problems/not-found",
            )
            return

        relative_path = requested_path or "index.html"
        normalized = os.path.normpath("/" + relative_path).lstrip("/")
        full_path = (self.state.static_dir / normalized).resolve()
        try:
            full_path.relative_to(self.state.static_dir)
        except ValueError:
            self.write_problem(
                404,
                "Not found",
                "The requested resource does not exist.",
                "https://example.invalid/problems/not-found",
            )
            return

        if not full_path.is_file():
            self.write_problem(
                404,
                "Not found",
                "The requested resource does not exist.",
                "https://example.invalid/problems/not-found",
            )
            return

        self.set_status(200)
        self.set_header("Content-Type", guess_content_type(full_path))
        self.write(read_file_bytes(full_path))


class NotFoundHandler(BaseHandler):
    def prepare(self) -> None:
        self.write_problem(
            404,
            "Not found",
            "The requested resource does not exist.",
            "https://example.invalid/problems/not-found",
        )
        self.finish()


@dataclass
class AppState:
    region_store: RegionStore
    capture_manager: CaptureManager
    static_dir: Path | None


def guess_content_type(path: Path) -> str:
    content_type, _ = mimetypes.guess_type(str(path))
    if content_type is None:
        return "application/octet-stream"
    if content_type.startswith("text/"):
        return f"{content_type}; charset=utf-8"
    if content_type in {
        "application/javascript",
        "application/json",
        "application/xml",
        "image/svg+xml",
    }:
        return f"{content_type}; charset=utf-8"
    return content_type


def make_app(state: AppState) -> tornado.web.Application:
    return tornado.web.Application(
        [
            (r"/api/v1/captures", CapturesHandler),
            (r"/api/v1/captures/([^/]+)", CaptureStatusHandler),
            (r"/api/v1/images/full", FullImageHandler),
            (r"/api/v1/images/region", RegionImageHandler),
            (r"/api/v1/regions", RegionsHandler),
            (r"/(.*)", StaticRootHandler),
        ],
        default_handler_class=NotFoundHandler,
        state=state,
        autoreload=False,
        debug=False,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Camera server")
    parser.add_argument("--host", default="127.0.0.1", help='Bind host (default "127.0.0.1")')
    parser.add_argument("--port", default=8080, type=int, help="Bind port (default 8080)")
    parser.add_argument(
        "--regions-file",
        default="regions.json",
        help="Path to the region configuration JSON file (default: ./regions.json)",
    )
    parser.add_argument(
        "--static-dir",
        default=None,
        help="Optional document root for non-/api URLs",
    )
    parser.add_argument(
        "--capture-dir",
        default=None,
        help="Directory for capture files (default: <tempdir>/camera-server)",
    )
    parser.add_argument(
        "--take-picture-cmd",
        default="take_picture.sh",
        help="Command used to capture a JPEG (default: take_picture.sh)",
    )
    parser.add_argument(
        "--wait-timeout",
        default=15.0,
        type=float,
        help="Maximum seconds to wait for blocking image requests (default: 15)",
    )
    return parser


def validate_args(args: argparse.Namespace) -> tuple[Path, Path | None, Path]:
    regions_path = Path(args.regions_file).resolve()
    static_dir = Path(args.static_dir).resolve() if args.static_dir else None
    if static_dir is not None and not static_dir.is_dir():
        raise SystemExit(f"error: --static-dir directory not found: {static_dir}")

    if args.capture_dir:
        capture_dir = Path(args.capture_dir).resolve()
    else:
        capture_dir = Path(tempfile.gettempdir()) / "camera-server"
    capture_dir.mkdir(parents=True, exist_ok=True)
    take_picture_resolved = shutil.which(args.take_picture_cmd) if os.sep not in args.take_picture_cmd else args.take_picture_cmd
    if take_picture_resolved is None:
        raise SystemExit(f"error: command not found: {args.take_picture_cmd}")
    return regions_path, static_dir, capture_dir


async def async_main(args: argparse.Namespace) -> None:
    regions_path, static_dir, capture_dir = validate_args(args)
    region_store = RegionStore(regions_path)
    capture_manager = CaptureManager(
        region_store=region_store,
        capture_root=capture_dir,
        take_picture_cmd=args.take_picture_cmd,
        wait_timeout=args.wait_timeout,
    )
    app = make_app(AppState(region_store=region_store, capture_manager=capture_manager, static_dir=static_dir))
    app.listen(args.port, address=args.host)
    print(f"Listening on http://{args.host}:{args.port}")
    await asyncio.Event().wait()


def main() -> int:
    args = build_parser().parse_args()
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
