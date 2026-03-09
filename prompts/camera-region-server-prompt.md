Camera Server
=============

2026-03-07


The objective is to design a camera web server in Python, Tornado and Pillow,
that implements the API explained in the Camera Server Region API (v1) document:
camera-server-region-api-v1.md. The idea is to capture a picture from the camera
and then rotate and crop regions out of it, for OCR purposes.

Each region is a rectangle that has a center position, size and rotation angle.
Center X goes from left to right, center Y goes from top to bottom of the
camera picture. Center X, center Y, width and height are in camera picture
pixels.

Rotation angle 0° is unrotated (region width is parallel to the X axis and
region height is parallel to the Y axis of the camera picture). Positive angles
rotate the region rectangle CCW, or the camera picture CW around the region
rectangle center. Rotated region should preserve as much quality as possible, by
using a suitable rotation algorithm (not "nearest neighbor").

Regions also have an index, a name and a description. The name is meaningful for
the server, but the description is just for a UI to display. Region index or
name can be used to download pictures from the camera server.

When taking a picture, the server should then process the configured regions and
generate JPEG files that can be served with the HTTP API. Temporary files should
be stored in a suitable place on a Linux filesystem, e.g.,
`/run/camera-server/*`. Maybe there is a Python module that can be used to find
a suitable directory in a cross-platform manner. The camera server itself is
not responsible for deleting old files. There is a separate system process for
that.

To take a picture, a script `take_picture.sh` is in PATH. It takes a single
command line argument, which is the output filename in JPEG format. The script
produces a lot of debugging text on stdout and stderr. Running it takes a few
seconds, so should probably be run in a worker thread. The `take_picture.sh`
script can be configured to save files in various resolutions, and the camera
server has to read the JPEG file to find out the size.
