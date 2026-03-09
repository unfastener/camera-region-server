Mock Camera Server
==================

2026-03-03


Can you create me a mock Python web server that has the following URL
endpoints? Use either the Tornado framework, or no framework at all.

Command line arguments:

"--host", default "127.0.0.1", "--port", default 8080, "FILE", mandatory


1.

Mock trigger taking a new picture. Returned JSON object is a hardcoded string,
with no real dynamic values. Response "Location:" header is likewise hardcoded.

Request: POST /api/v1/captures

Request body: empty

Response: 201 Created

Response headers:

    Location: /api/v1/captures/1709299200.123456-8f3b2c

Response body:

    {
    "capture_id": "1709299200.123456-8f3b2c",
    "timestamp": 1709299200.123456,
    "status": "ready"
    }


2.

Return a mock status JSON object. The JSON object is a hardcoded string, with
no real dynamic values. In the request URL, anything after "captures/" is
ignored.

Request: GET /api/v1/captures/*

Response: 200 OK with Content-Type: application/json

Response body:

    {
        "capture_id": "1709299200.123456-8f3b2c",
        "timestamp": 1709299200.123456,
        "status": "ready",
        "assets": {
            "full_jpeg": "/api/v1/images/full?capture_id=1709299200.123456-8f3b2c"
        }
    }


3.

Return the full-frame image as a JPEG, set as a command line parameter.

Query parameters, if any, are ignored. "X-Capture-*" headers have hardcoded
values.

Request: GET /api/v1/images/full

Response: 200 OK with Content-Type: image/jpeg

Response body: the JPEG image

Response headers:

    X-Capture-Id: 1709299200.123456-8f3b2c
    X-Capture-Timestamp: 1709299200.123456


4.

Mock get regions. Always returns a hardcoded JSON response.

Request: GET /api/v1/regions

Response: 200 OK with Content-Type: application/json

Response body:

    {
        "version": 1,
        "regions": []
    }


5.

Mock set regions. Returns a hardcoded error.

Request: PUT /api/v1/regions

Request body: ignored

Response: 400 Bad Request with Content-Type: application/problem+json

Response body:

    {
        "type": "about:blank",
        "title": "Bad Request",
        "status": 400
    }


6.

Any other request will result in a hardcoded response.

Response: 404 Not Found with Content-Type: application/problem+json

Response body:

    {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404
    }
