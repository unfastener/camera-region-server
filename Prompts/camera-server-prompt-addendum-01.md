Camera Server Addendum 01
=========================

2026-03-07


In order to be able to serve static files, the camera server should take a
command line argument for a path, and serve any URLs (except `/api`) from
there. For example, a URL `/index.html` should be served as a static file
`<PATH>/index.html`, where `<PATH>` is the value of the command line argument.

MIME types should be used, based on filename suffix. Encoding for text files is
always UTF-8.
