Camera Server Region API
========================

2026-03-01


Let's design an HTTP API for a special camera server. There is a single camera
pointed at one or more details of interest. The idea is to capture an image and
crop and rotate regions out of it and serve those over HTTP.

The server is behind a reverse proxy that does HTTPS and authentication. It can
not be accessed directly. Therefore, the protocol is plain HTTP with no
authentication.

The API should have the following features:

 - Trigger a picture-taking event

   - Timestamp of the event (e.g., a UNIX timestamp with fractional seconds)
     is returned. This timestamp is "opaque" to the client. The client cannot
     ask for other timestamps besides those returned by the server.
   - Depending on the state of the camera hardware, taking a picture may take
     several seconds.

 - Get the full image as JPEG, without any cropping and rotating

   - Request must refer to a specific timestamp, or if omitted, a new picture
     taking event is triggered.
   - Response must contain the timestamp of the picture-taking event.
   - If a new picture-taking event is triggered or the picture is still being
     taken, this operation may take several seconds before a response is
     returned.
   - An HTTP error is returned if the camera hardware is not working properly.

 - Get a specific region of the picture as JPEG

   - Cropped and rotated by the server, based on region definitions
   - Server may choose to do the cropping and rotating when the picture is
     taken, or when the request comes in. This will affect the time it takes
     a response to be returned.
   - A region number or name (not both) must be included in the request.
   - Request must refer to a specific timestamp, or if omitted, the server is
     free to choose any other cached picture (e.g., the latest), or return
     an HTTP error code if there are no cached pictures.

 - Get the region definitions

   - The server returns a JSON object of all previously defined areas.

 - Set the region definitions

   - The server deletes previously defined areas and sets the new ones from
     the request JSON object.
   - If the request format is invalid, old regions remain unchanged and an
     HTTP error is returned.


Regions are stored in a JSON ​object as an array. Each region is:

 - A region number starting from 0, no gaps

   - This is perhaps implicit as an array index?

 - A region name

   - Must be a valid C, Python, Rust and JavaScript variable name

 - A region description

   - Up to 256 character Unicode free-form string
   - Not used by the server

 - Region position, size and 2D rotation angle

   - In whichever format that is easy to use by the server



Further Prompts
===============

Coordinate System
-----------------

I need the region image to be a rectangle, with contents from the original
image. If I crop first and rotate second, I end up with a rectangle that is not
axis aligned, and a bunch of transparent or solid color pixels. Is there a way
to define the coordinates and angle in such a way that the "virtual source
rectangle" is rotated instead, and the result is always an axis-aligned
rectangle?


Curly Braces Clarification
--------------------------

In `GET /api/v1/captures/{capture_id}` are the curly braces there for real, or
just a typographical detail?


Full Image API Harmonization
----------------------------

Here is a specification for a camera server HTTP API. I want to do some edits.

The API version stays the same, as there are no implementations of it, yet.

Let's harmonize the `GET /api/v1/images/full` and GET `/api/v1/images/region`
requests and responses:

I want the full image semantics to be like the region semantics: if `capture_id`
is missing, the server is free to return a cached capture, or an error if none
exists. A new capture can be triggered by omitting `capture_id` and giving a
parameter `new_capture=true` (defaults to `false`). If a capture is already in
progress, no new capture will be started. The correct Capture ID and timestamp
is returned in the headers.

I want to clarify the source: `[auto|on_demand]` parameter:

`source` (optional, default `auto`): one of `auto`, `on_demand`, where the
server decides whether to crop-at-capture or crop-on-demand (hint; server may
ignore). On-demand cropping may cause slower response from the server.

I want a Markdown file with the edits, but it cannot be embedded here. It
must be a downloadable link.
