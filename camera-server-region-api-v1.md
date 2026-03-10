# Camera Server Region API (v1)

Date: 2026-03-01

This document specifies a plain-HTTP API intended to run behind an HTTPS reverse proxy that provides authentication and TLS. The server **must not** rely on direct client access, TLS, or authentication at this layer.

- Base path: `/api/v1`
- JSON media type: `application/json; charset=utf-8`
- Error media type: `application/problem+json` (RFC 9457-style)

---

## Concepts

### Capture

A **capture** is a picture-taking event that produces a full-frame image and (optionally) derived region images.

Each capture is identified by an **opaque** string:

- `capture_id` (opaque): clients MUST treat it as an uninterpreted identifier and MUST only use values returned by the server.

The server MAY also expose a numeric timestamp for debugging or logging:

- `timestamp` (number): UNIX time in seconds, MAY include fractional seconds.
  - Clients MUST treat `capture_id` as the authoritative identifier even if `timestamp` is present.

### Regions

A **region** defines a rectangular output image produced by sampling the original image with an affine transform (rotated sampling grid). The returned region image is always an **axis-aligned rectangle** (JPEG) of the requested `width × height`.

Regions are stored as an array with implicit indices:

- Region index is the array index: `0..N-1` (no gaps by construction).
- Each region also has a unique `name`.

---

## Headers

### Image responses (recommended)

On `200 OK` responses with `Content-Type: image/jpeg`, the server SHOULD include:

- `X-Capture-Id: <capture_id>`
- `X-Capture-Timestamp: <unix_seconds_with_fraction>` (optional)
- For region images:
  - `X-Region-Index: <int>` and/or `X-Region-Name: <name>`

### Status / async responses (recommended)

For `202 Accepted` the server SHOULD include:

- `Location: /api/v1/captures/<capture_id>`
- `Retry-After: <seconds>` (integer)

---

## Error format

Errors MUST be returned as `application/problem+json`:

```json
{
  "type": "https://example.invalid/problems/invalid-parameters",
  "title": "Invalid parameters",
  "status": 400,
  "detail": "Exactly one of 'index' or 'name' must be provided.",
  "instance": "/api/v1/images/region"
}
```

Common status codes used by this API:

- `400 Bad Request` — invalid parameters or JSON
- `404 Not Found` — unknown `capture_id` or missing region
- `409 Conflict` — no cached captures available (when allowed behavior is “choose cached”)
- `412 Precondition Failed` — ETag precondition failed on region update
- `422 Unprocessable Entity` — region geometry out of bounds (strict mode)
- `503 Service Unavailable` — camera hardware unavailable
- `504 Gateway Timeout` — blocking wait exceeded server timeout

---

## Endpoints

### 1) Trigger a picture-taking event

#### `POST /api/v1/captures`

Starts a new capture.

The server MAY complete quickly or may take several seconds depending on camera hardware state.

**Request body:** empty

**Responses**

- `201 Created` (capture completed immediately) or `202 Accepted` (capture started)
- `503 Service Unavailable` if camera hardware not working properly

**Response JSON**

```json
{
  "capture_id": "1709299200.123456-8f3b2c",
  "timestamp": 1709299200.123456,
  "status": "processing"
}
```

**Headers**

- `Location: /api/v1/captures/1709299200.123456-8f3b2c`

---

### 2) Get capture status

#### `GET /api/v1/captures/<capture_id>`

Returns capture state and (optionally) links to assets.

> Note: Angle brackets in this spec denote placeholders. They are not literal characters in the URI.

**Responses**

- `200 OK`
- `404 Not Found` if `capture_id` is unknown/expired

**Response JSON**

```json
{
  "capture_id": "1709299200.123456-8f3b2c",
  "timestamp": 1709299200.123456,
  "status": "ready",
  "assets": {
    "full_jpeg": "/api/v1/images/full?capture_id=1709299200.123456-8f3b2c"
  }
}
```

`status` is one of:

- `processing`
- `ready`
- `failed`

If `failed`, include diagnostic fields:

```json
{
  "capture_id": "1709299200.123456-8f3b2c",
  "timestamp": 1709299200.123456,
  "status": "failed",
  "error_code": "camera_error",
  "message": "Sensor timeout"
}
```

---

### 3) Get the full image as JPEG

#### `GET /api/v1/images/full`

Returns the full-frame image as a JPEG.

**Query parameters**

- `capture_id` (optional):
  - If provided: return that capture’s full image.
  - If omitted: server MAY choose a cached capture (e.g. latest), OR return an error if none exist.
- `new_capture` (optional, default `false`):
  - If `true` and `capture_id` is omitted: request that the server start (or reuse) an in-progress capture for this response.
  - If a capture is already in progress, the server MUST NOT start another new capture.
- `wait` (optional, default `true`): same semantics as region image.
  - `true`: server MAY block until ready (up to server timeout).
  - `false`: server MUST NOT block; if not ready, return `202 Accepted`.

**Responses**

- `200 OK` with `Content-Type: image/jpeg`
- `202 Accepted` if capture is not ready and `wait=false` (or server chooses not to block)
- `404 Not Found` if `capture_id` is unknown/expired
- `409 Conflict` if `capture_id` is omitted and no cached captures exist (and `new_capture=false`)
- `503 Service Unavailable` if camera hardware not working properly and a new capture is required (`new_capture=true`)
- `504 Gateway Timeout` if `wait=true` and capture did not become ready within timeout

On `200 OK`, response headers SHOULD include `X-Capture-Id` (and optionally `X-Capture-Timestamp`).

---

### 4) Get a region of a picture as JPEG

#### `GET /api/v1/images/region`

Returns a cropped-and-rotated region derived from the original image, encoded as a JPEG.

The output is always an axis-aligned rectangle of size `width × height` defined by the region.

**Query parameters**

Exactly one of:

- `index` — integer region index (0..N-1)
- `name` — region name

Additionally:

- `capture_id` (optional):
  - If provided: derive from that capture.
  - If omitted: server MAY choose a cached capture (e.g. latest), OR return an error if none exist.
- `wait` (optional, default `true`): same semantics as full image.
- `source` (optional, default `auto`): one of `auto`, `on_demand`, where the server decides whether to crop-at-capture or crop-on-demand (hint; server may ignore).
  - On-demand cropping MAY cause slower response from the server.

**Responses**

- `200 OK` with `Content-Type: image/jpeg`
- `202 Accepted` if capture/derivation not ready and server won’t block
- `400 Bad Request` if both/neither of `index` and `name` are provided, or invalid parameter types
- `404 Not Found` if region doesn’t exist or `capture_id` unknown/expired
- `409 Conflict` if `capture_id` omitted and no cached captures exist
- `422 Unprocessable Entity` if region sampling would go out of bounds (strict mode)
- `503 Service Unavailable` if camera hardware not working properly and a new capture is required

On `200 OK`, response headers SHOULD include:
- `X-Capture-Id`
- `X-Region-Index` and/or `X-Region-Name`

---

### 5) Get region definitions

#### `GET /api/v1/regions`

Returns all currently configured regions.

**Responses**

- `200 OK`

**Response JSON**

```json
{
  "version": 12,
  "regions": [
    {
      "name": "water_meter_left",
      "description": "Left meter register",
      "geometry": {
        "cx": 1520.5,
        "cy": 780.25,
        "width": 640,
        "height": 320,
        "rotation_deg": -1.25
      }
    },
    {
      "name": "water_meter_right",
      "description": "Right meter register",
      "geometry": {
        "cx": 2250.0,
        "cy": 780.0,
        "width": 640,
        "height": 320,
        "rotation_deg": 0.75
      }
    }
  ]
}
```

**Notes**

- Region index is implicit: array index `0..N-1`.
- `version` MUST increment on every successful update.

**Headers (recommended)**

- `ETag: "regions-v12"`
- `Cache-Control: no-cache`

---

### 6) Set region definitions (atomic replace)

#### `PUT /api/v1/regions`

Replaces the entire region list atomically.

If the request is invalid, **old regions remain unchanged**.

**Request headers**

- `Content-Type: application/json`
- Optional concurrency control (recommended):
  - `If-Match: "regions-v12"`

**Request JSON**

```json
{
  "regions": [
    {
      "name": "water_meter_left",
      "description": "Left meter register",
      "geometry": { "cx": 1520.5, "cy": 780.25, "width": 640, "height": 320, "rotation_deg": -1.25 }
    }
  ]
}
```

**Responses**

- `200 OK` (or `204 No Content`) on success
- `400 Bad Request` for invalid JSON/schema (no change applied)
- `412 Precondition Failed` if `If-Match` is present and does not match current ETag

**Response JSON on success (if returning body)**

```json
{
  "version": 13,
  "regions": [ /* as stored */ ]
}
```

**Headers on success (recommended)**

- `ETag: "regions-v13"`

---

## Region definition schema

Each region object:

- `name` (string, required)
  - Must be a valid C / Python / Rust / JavaScript identifier.
  - Regex: `^[A-Za-z_][A-Za-z0-9_]*$`
- `description` (string, optional)
  - Unicode string, maximum length 256 characters.
  - Not used by the server (metadata only).
- `geometry` (object, required)

### Geometry (rotated sampling grid; axis-aligned output)

`geometry` fields:

- `cx` (number, required): center X coordinate in source image pixels
- `cy` (number, required): center Y coordinate in source image pixels
- `width` (integer, required): output width in pixels, `> 0`
- `height` (integer, required): output height in pixels, `> 0`
- `rotation_deg` (number, required): rotation angle in degrees
  - Positive angles follow the image-coordinate convention defined below.
  - Range is not constrained by the API, but `[-180, 180)` is recommended for readability.

### Coordinate convention

Image coordinates use the usual raster convention:

- origin `(0, 0)` is the top-left corner of the source image
- `x` increases to the right
- `y` increases downward

Under this convention, positive `rotation_deg` is mathematically counterclockwise in `(x, y)` coordinates, but may appear visually clockwise to implementers who are used to Cartesian coordinates with positive `y` upward. Implementers MUST follow the sampling equations below rather than relying on intuition about clockwise/counterclockwise appearance.

### Semantics (normative)

For each output pixel `(u, v)` where `u = 0..width-1` and `v = 0..height-1`, define:

- `du = u - (width - 1) / 2`
- `dv = v - (height - 1) / 2`
- `theta = rotation_deg * pi / 180`
- Then the source coordinate to sample is:

  - `x = cx + du*cos(theta) - dv*sin(theta)`
  - `y = cy + du*sin(theta) + dv*cos(theta)`

The server samples the source image at `(x, y)` (e.g., bilinear interpolation) and writes the result to output pixel `(u, v)`.

This produces an axis-aligned output rectangle of exactly `width × height` with contents taken from the original image.

This definition is authoritative. In other words, the API defines an **output-pixel to source-image** mapping.

### Important implementation note

Many imaging libraries do **not** ask for this mapping directly.

- If a library expects an **output-to-source** transform, use the equations above directly.
- If a library expects a **source-to-output** transform, you MUST invert the transform before passing it to the library.
- If a library uses a flag or mode for “inverse map”, enable that mode when appropriate.

A common implementation bug is to negate `rotation_deg` incorrectly because the implementer mixes up:

- image coordinates (`y` downward) vs Cartesian coordinates (`y` upward)
- output-to-source transforms vs source-to-output transforms

Implementers SHOULD verify the sign using a non-symmetric test image, such as text, an arrow, or a digit display.

### Worked example

Example region:

- `cx = 100`
- `cy = 50`
- `width = 3`
- `height = 1`
- `rotation_deg = 90`

Then:

- output pixel `(0, 0)` has `du = -1`, `dv = 0`, so it samples source `(100, 49)`
- output pixel `(1, 0)` has `du = 0`, `dv = 0`, so it samples source `(100, 50)`
- output pixel `(2, 0)` has `du = 1`, `dv = 0`, so it samples source `(100, 51)`

So with `rotation_deg = 90`, moving rightward in the output image corresponds to moving downward in the source image.

### Out-of-bounds behavior

If any sampled coordinates fall outside the source image bounds, the server MUST choose one of these policies and apply it consistently:

- **Strict (recommended):** return `422 Unprocessable Entity`
- **Border fill:** fill with a constant color (implementation-defined)
- **Clamp/replicate:** clamp sampling coordinates to edge pixels

If strict mode is used, `422` SHOULD include a problem detail explaining which region is out of bounds.

---

## Caching (recommended)

- Regions:
  - `Cache-Control: no-cache`
  - Use `ETag` + `If-Match` for safe updates
- Images:
  - Captures are immutable. If safe in your deployment:
    - `Cache-Control: private, max-age=31536000, immutable`
  - If you do not want clients/proxies caching images:
    - `Cache-Control: no-store`

---

## Examples

For rotation behavior and transform direction, see the worked example in the Geometry section above. Implementers SHOULD verify their image-library mapping against that example before relying on visual intuition alone.

### Trigger capture

```http
POST /api/v1/captures HTTP/1.1
Host: camera.local
```

```http
HTTP/1.1 202 Accepted
Location: /api/v1/captures/1709299200.123456-8f3b2c
Content-Type: application/json; charset=utf-8

{"capture_id":"1709299200.123456-8f3b2c","timestamp":1709299200.123456,"status":"processing"}
```

### Poll capture status

```http
GET /api/v1/captures/1709299200.123456-8f3b2c HTTP/1.1
Host: camera.local
```

### Get full image (cached if available)

```http
GET /api/v1/images/full HTTP/1.1
Host: camera.local
```

### Get full image (request a new capture)

```http
GET /api/v1/images/full?new_capture=true HTTP/1.1
Host: camera.local
```


### Get region by name from latest cached capture

```http
GET /api/v1/images/region?name=water_meter_left HTTP/1.1
Host: camera.local
```

### Replace regions

```http
PUT /api/v1/regions HTTP/1.1
Host: camera.local
Content-Type: application/json
If-Match: "regions-v12"

{"regions":[{"name":"water_meter_left","description":"Left meter","geometry":{"cx":1520.5,"cy":780.25,"width":640,"height":320,"rotation_deg":-1.25}}]}
```
