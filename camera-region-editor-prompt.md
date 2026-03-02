Camera Region Editor
====================

2026-03-02


Let's design a web UI that provides an easy and intuitive way to view and edit
camera regions as explained in the accompanying Camera Server Region API (v1)
document. The idea is to capture a picture from the camera and then be able to
view, edit, add and delete regions of interest based on that picture.

The server does the image cropping and rotating based on region definitions.
These rotated and cropped images are used for OCR purposes, outside of this web
UI.

The purpose of this web UI is to visually create these region definitions by
allowing the user to draw region wireframe boxes, position them, rotate them,
enter names and descriptions, delete them, load them from the server and save
any changes to the server, as well as load / save local files for backup
purposes.

Each region is a rectangle that has a center position, size and rotation angle.
Center X goes from left to right, center Y goes from top to bottom of the
camera picture. Center X, center Y, width and height are in camera picture
pixels. Rotation angle 0° is unrotated (region width is parallel to the X axis
and region height is parallel to the Y axis of the camera picture) and positive
angles are CCW.

Regions also have an index, a name and a description. The name is meaningful for
the server, but the description is just for display. Region index or name can be
used to download pictures from the camera server, but that feature is unused in
this web UI.


Screen Layout
-------------

The top part of the screen consists of a small logo, some push buttons, text
fields and a region selector drop-down. The remaining part of the screen is the
camera picture, which is a static JPEG, not a video stream.

While a camera picture is being loaded, a spinner is shown on top of the camera
picture area. The spinner graphic should be easily replaceable, to match the
design of the rest of the page.

Wireframe region boxes are drawn on top of the camera picture. When no picture
is yet loaded, no wireframe region boxes are displayed either, because they
have to be scaled to the displayed image width and height. If camera picture
dimensions change, the region wireframe boxes will be adjusted to match the new
camera picture.

The largest region index is drawn first (behind everything else) and region
index 0 is drawn last (on top), except that the selected region is drawn on top
of all other regions.

Concept art:

```
[Logo] <Refresh> <Region___0:_Cold_water_gauge____> <Next> <Add> <Save>   <File Save>
       [Last re] <Shows_the_cold_water_consumption> <Prev> <Del> <Revert> <File Load>

+---------------------------------------------------------------------------------------+
|                                                                                       |
|                                                                                       |
|                                                                                       |
|                                                                                       |
|                                                                                       |
|                                                                                       |
|                                                                                       |
|                                                                                       |
|                                     Camera Picture JPEG                               |
|                                                                                       |
|                                                                                       |
|                                                                                       |
|                                                                                       |
|                                                                                       |
|                                                                                       |
|                                                                                       |
+---------------------------------------------------------------------------------------+
```


 - `[Logo]`: A small logo, as tall as the two rows of UI controls

 - `<Refresh>`: A button to get the latest camera picture from the server

   - Always requests a new capture event

 - `[Last re]`: Timestamp of last refresh (or blank if none), small text in a human readable format

 - `<Region___0:_Cold_water_gauge___>`: Currently selected region, a selector menu and a text field

   - Clicking "Region___0:" drops down a menu of all regions and their names.

   - Clicking "Cold_water_gauge___" edits the name.

 - `<Shows_the_cold_water_consumption>`: Region description, a text field

 - `<Prev>`: A button that selects the previous region (wrap around)

 - `<Next>`: A button that selects the next region (wrap around)

 - `<Add>`: A button to add a new region, with default name, placement, rotation

 - `<Del>`: A button to delete the currently selected region

 - `<Save>`: A button to save edited region definitions to the server

 - `<Revert>`: A button to load region definitions from the server, forgetting any edits

 - `<File Save>`: A button to save edited region definitions to a file with the browser

 - `<File Load>`: A button to replace edited region definitions with a file from the browser


Although the buttons have text in this concept art, it is probable that some or
most of them will have icons instead in the final product.

The region wireframe box looks like this:

```
           X
+------+--------------O
|  10  |              |
+------+              |X
|                     |
+---------------------+
```

`|` and `-` are wireframe lines. `+` denotes corners. This is just for clarity
in this document. In reality, the wireframe boxes are drawn without anything
special in the corners.

`O` is the rotation handle, `X` is the width or height handle. These are only
visible when the region is selected.

Every aspect of the region wireframe box is under CSS control: color, line
width, border or shadow, font, text size, etc.

All region wireframe boxes are shown at all times. The selected region box is
emphasized by setting the wireframe color to yellow (under CSS control). Other
regions have grey wireframe color (also under CSS control). The selected region
box also has the control handles visible. The others will not.

The region index (here `10`) is displayed in a filled rectangle in the top left
corner of the region rectangle. The fill color is the same as the wireframe
color.

When the region wireframe box is rotated, everything rotates: lines, text,
filled rectangles. There is no attempt to keep anything upright.

The whole region wireframe and the filled rectangle have a thin black border,
so that they are visible over various different backgrounds.

The page scales to fit the visible browser window. The camera picture scales,
preserving proportions, to take as much space as possible below the controls.
There will be no scrolling, unless the browser window is way too small.

Mobile responsive layout will be designed at a later stage. The initial UI will
be run on a high-resolution PC screen.


Mouse, Touch and Keyboard Interactions
--------------------------------------

When the page loads, it will initially have a placeholder solid color displayed.
The first camera picture is loaded automatically, as if the user had pressed the
`<Refresh>` button, causing a spinner to be displayed.

The UI only uses `wait=true`, blocking reads. If a picture load fails, the
previous picture, or a placeholder solid color, keeps being used. There will be
no error message at this revision (may be implemented later).

Also when the page loads, region definitions are automatically loaded from the
server, as if the `<Revert>` button was pressed. The first region will become
the selected one. Until the first camera picture loads, no region wireframe
boxes will be shown on the camera picture area, as they need to know the picture
size to be able to be shown correctly.

The two actions above can occur in any order.

Limited functionality is available until a camera picture is loaded. Button
`<Refresh>` is dimmed and unclickable whenever a picture loading is in progress.
Likewise, `<Add>` is dimmed and unclickable before a picture is loaded, because
picture dimensions are not known yet.

Almost no functionality is available until the initial region definitions are
loaded. Buttons `<Prev>`, `<Next>`, `<Add>`, `<Del>`, `<Save>`, `<Revert>`,
`<File Save>` and `<File Load>` remain dimmed and unclickable while region
definitions are being loaded. If loading fails, `<Revert>` and `<File Load>` get
enabled. It is then possible to retry, or use a local file as the source of the
region definitions. `<Save>` and `<File Save>` become available when there are
region definitions available and no load or save in progress.

`<Save>` button has a Unicode BULLET symbol U+2022 in front, if there are
edits between the server and the local state. This is called the "dirty" flag.
After successfully saving to, or loading from the server, the "dirty" flag is
cleared. Any change will set the "dirty" flag again:

 - Moving, rotating or resizing a region, or editing the name or description

   - Even if the user somehow was able to come up with exactly the
     same values that are stored on the server, with the web UI interface

   - In other words, do not compare the values. Just set the "dirty" flag on
     most user interactions, for simplicity.

 - Adding or deleting regions

 - Implicit clamping of region data to minimum / maximum

   - Can even theoretically happen when loading from the server

 - Loading new data from a file with `<File Load>`


There will always be a selected region, except when there are no regions
defined. The selected region box is highlighted in the emphasis color (yellow).
All other region boxes (if any) will be set to the not-emphasized color (grey).

Clicking on a region box will select it. The region selector on the top of the
page will change to show details of the newly selected region. If there are two
or more region boxes at the click coordinates, priority is at the already
selected region, then from the one where the center position is the closest to
the click position.

Only the selected region can be moved, rotated or resized. A region must be
first selected by clicking at it, before it can be modified in any other way.

Conversely, selecting another region from the region selector, or pressing the
`<Next>` or `<Prev>` buttons will choose another region and emphasize its
region wireframe box.

The selected region box will display control handles in the same color and
style as the wireframe and region index rectangle:

 - Center position: The whole wireframe rectangle, not drawn separately

 - Rotation: A filled circle in the top right corner

 - Width: A filled square on the right edge midpoint, outside the wireframe

 - Height: A filled square on the top edge midpoint, outside the wireframe


Grabbing and dragging these handles will adjust the chosen parameter in an
intuitive fashion:

 - Center position: drags the center of the region box around in the camera
   picture coordinate frame

 - Rotate:

   - Convention: rotation_deg = 0 means the region is unrotated (its width axis
     is parallel to +X of the original picture and its height axis is parallel
     to +Y). Positive angles rotate the region counterclockwise.

   - Interaction: Dragging the rotation handle sets rotation_deg based
     on the angle of the cursor vector from the region center, using image
     coordinates (+X right, +Y down) with the conventional CCW sign:

     rotation_deg = atan2(-(cursor_y - center_y), (cursor_x - center_x))
     converted to degrees

     The rotation handle’s placement (top-right corner) is only for hit-testing
     and does not define the 0° direction.

     Example: cursor to the right of center is 0°, up from center is 90°.

 - Width, height: sets the width and height based on the distance from the
   center position, taking rotation into account. Visually, the right or top
   edge of the region box, extended to infinity, will intersect with the cursor.


The center position is not really a handle. Grabbing anywhere within the
rectangle will position it.

Handle priorities, in case they overlap:

  - Width
  - Height
  - Rotation
  - Center position


The minimum width of a region is 64 pixels and the minimum height is 32 pixels.
Any loaded regions will be clamped to these sizes. (No warning message will be
printed at this stage, but may be added in future revisions.)

The width handle is at most 50% x 50% square of the region width. The height
handle is at most 50% x 50% square of the region height. The rotation handle has
a diameter that is at most 50% of the smaller of the region width or height. The
maximum size of any of the handles is a bounding box of 5% x 5% of the camera
picture, whichever is larger. Minimum size overrides the maximum size, if they
are in conflict.

When the `<Add>` button is pressed, a new region is added in the end:

 - Name: "region_NNN"
   - "NNN" is an integer counter, starting at 0. If a name is taken, add one and
     try again.
 - Description: "" (sent to server even if empty)
 - Position: <Center of loaded picture>
 - Width, height: <About 20% of loaded picture>
 - Rotation: 0


The new region will become selected.

After pressing the `<Del>` button, the region after it becomes the selected
one, or if it was the last one, the one before it.

None of the changes are uploaded to the server until the `<Save>` button is
pressed. The user may do any kinds of edits and either send them to the server
or not, as needed. Some details:

 - Coordinates may exceed the camera picture boundaries. This is allowed.

   - No `422` errors expected. Server is configured accordingly.

 - The UI doesn't care about versioning. When the user presses `<Save>`, no
   matter what changes have occurred in the meantime, all will be overwritten.
   No `ETag`, no `If-Match`.


Buttons and text fields may have keyboard accelerators, but those are not
decided yet. Wireframe region box may also be controlled using the keyboard,
but that is also not defined as of this writing.

For now, destructive actions like `<Del>` and `<Revert>` will not have
confirmation. This may be added in a future revision.


Styling
-------

The page follows a style already set by the rest of the website, which looks
like this:

```css
    :root {
      --gap: 16px;
      --fg: #fff;
      --bg: #292929;
      --button-fg: #666;
      --button-bg: rgb(30,30,30);
      --drop-shadow: 0 8px 20px rgba(0,0,0,0.35);
      --stream-bg: #000;
    }

    html, body {
      height: 100%;
      margin: 0;
      background: var(--bg);
      color: var(--fg);
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    }

    .page {
      min-height: 100%;
      display: flex;
      flex-direction: column;
      box-sizing: border-box;
      padding: var(--gap);
      gap: var(--gap);
    }

    .title {
      width: 80vh;
      max-width: 1174px;
      max-height: 253px;
      aspect-ratio: 1174 / 253;
      margin: 0 auto;

      background: url("/title.png") no-repeat center / contain;
      color: transparent;

      user-select: none;
      caret-color: transparent;
    }

    .wrap {
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      box-sizing: border-box;
    }

    .grid {
      width: 100%;
      max-width: 1800px;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: var(--gap);
    }

    .card {
      position: relative;
      min-width: 0;
      border-radius: 12px;
      overflow: hidden;
      box-shadow: var(--drop-shadow);
      user-select: none;
    }
```

```html
<body>
  <div class="page">
    <h1 class="title">Page Title</h1>

    <div class="wrap">
      <div class="grid">
        <div class="card">
          Contents 1
        </div>

        <div class="card">
          Contents 2
        </div>
      </div>
    </div>
  </div>
</body>
```

Colors and shadows, etc. should be consistent with the above. Layout is
different, of course. The camera picture should be a card, with rounded corners
and a shadow. Buttons and text fields should also have rounded corners and
shadows.

There should be no external dependencies. If icons or other assets are required,
they will be individually saved as SVGs, PNGs or data URLs.


File Structure
--------------

Everything should be in one HTML file, with embedded CSS and JavaScript. If
there is need for external assets like icons, those will be provided as needed.

The page logo is a file that already exists, but the dimensions cannot be
disclosed at this time.

All external assets will be served from the same host as the page itself. All
URLs can omit the protocol, server and port part.


Other Technical Details
-----------------------

There is no user facing error messaging of any kind. This is deliberate. They
may get added later, but the environment is so well constrained that it is
likely not needed.

The server API is configured to tolerate any (mis)behavior of the UI. This
prompt will be updated if there are any grave issues.

The UI doesn't care about caching and knowns nothing about `capture_id`. All API
calls cause explicit action on the server. There are other API consumers that
need all the fancy features. This UI doesn't.

The web UI will always do blocking reads, starts new captures
(`new_capture=true`), ignores `ETag` versioning headers or any notion of
concurrency, really, and generally behave like everything was set up perfectly
for it. Which it kind of is. The API was deliberately designed to allow such
use.

Rotation angles will be fixed in the backend, if there is any discrepancy. Or
in this prompt. This is difficult to get right and requires concrete iteration.

Region indices are displayed just as a hint to the user. The API considers the
indices important, but for the web UI, indices are just a short label to show
on-screen. Adding and deleting regions changes the indices, and the user is
perfectly OK with that. Other consumers of the API will use the indices for
iteration purposes, and use the region names for random access.
