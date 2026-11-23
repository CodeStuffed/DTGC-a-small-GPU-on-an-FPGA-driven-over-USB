"""Usage, in Fusion's Text Commands box with Py selected, with the case from scripts/case_fusion.py open:
    exec(open(r"C:\\Users\\User\\Documents\\tinygpu\\scripts\\case_render.py").read())

Makes ray-traced preview pictures of the case in docs/images. They show the CAD model, not a real print. The colours
are the ones scripts/case_fusion.py gave the two parts: a dark tray and a pale lid.
"""
import math
import os
import time

import adsk.core
import adsk.fusion

PICTURES = r"C:\Users\User\Documents\tinygpu\docs\images"
CM = 0.1
BACKDROP = (150, 156, 166)
WIDTH, HEIGHT = 1600, 1000
VIEW = 26            # how wide the picture's view is, degrees. A narrow view keeps the box's sides from leaning in
FILL = 0.80          # how much of the picture the case may take up, the rest is left for its shadow
# The picture keeps the width of Fusion's window, and the camera's angle is measured over a height that is this
# fraction of the window's. Measured on this PC from four test pictures of a box of known size; VERIFY on another PC
# by checking that the case fills the pictures.
VIEW_HEIGHT = 0.936
LIGHT = 1.05         # turns the lighting around the case, in radians; picked from a sweep of 12 directions
LIFT = 16            # how far the lid is raised in the open picture, mm
SECONDS = 420        # longest wait for one picture


def set_all(thing, values):
    """Sets each setting that this version of Fusion has, and says which it does not."""
    for name, value in values.items():
        try:
            if not hasattr(thing, name):
                raise AttributeError(name)
            setattr(thing, name, value)
        except Exception as error:
            print("could not set", name, "-", str(error).splitlines()[0][:80])


def to_scene(v):
    """A point or direction of the model, where z is up, in the turned scene, where y is up."""
    return (v[0], v[2], -v[1])


def turn_for_pictures(design, lift=None):
    """Turns the parts so that the model's z is the scene's y, and gives back where they were.

    The lighting and the ground of Fusion's render scene are made for y pointing up. With z up, the long side of the
    case faces the ground and comes out black whatever the lighting. lift raises the lid by that many mm.
    """
    turn = adsk.core.Matrix3D.create()
    turn.setToRotation(-math.pi / 2, adsk.core.Vector3D.create(1, 0, 0), adsk.core.Point3D.create(0, 0, 0))
    homes = []
    for occurrence in design.rootComponent.occurrences:
        home = occurrence.transform2
        homes.append((occurrence, home))
        turned = home.copy()
        turned.transformBy(turn)
        if lift and "lid" in occurrence.component.name:
            moved = turned.translation
            turned.translation = adsk.core.Vector3D.create(moved.x, moved.y + lift * CM, moved.z)
        occurrence.transform2 = turned
    adsk.doEvents()
    return homes


def put_back(homes):
    for occurrence, home in homes:
        occurrence.transform2 = home
    adsk.doEvents()


def box_corners(low, high):
    return [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]


def camera_distance(corners, centre, direction, half_wide, half_high):
    """How far back along direction the camera must be for every corner to be inside the picture, in the same units.

    half_wide and half_high are the tangents of half the picture's view, across and up. Everything is in the scene's
    axes, where y is up.
    """
    length = math.sqrt(sum(v * v for v in direction))
    back = [v / length for v in direction]                      # from the centre towards the camera
    right = (back[2], 0.0, -back[0])                            # up x back, for up = y
    right_length = math.sqrt(right[0] ** 2 + right[2] ** 2)
    right = [v / right_length for v in right]
    up = (back[1] * right[2] - back[2] * right[1], back[2] * right[0] - back[0] * right[2],
          back[0] * right[1] - back[1] * right[0])
    furthest = 0.0
    for corner in corners:
        offset = [c - m for c, m in zip(corner, centre)]
        towards = sum(a * b for a, b in zip(offset, back))
        across = abs(sum(a * b for a, b in zip(offset, right)))
        above = abs(sum(a * b for a, b in zip(offset, up)))
        furthest = max(furthest, towards + across / (FILL * half_wide), towards + above / (FILL * half_high))
    return furthest, back


def render_one(rendering, viewport, low, high, direction, path):
    """low and high are opposite corners of the box around what is shown, direction is from it towards the camera.

    All three are in the model's own axes, in mm.
    """
    corners = [to_scene(corner) for corner in box_corners(low, high)]
    centre = to_scene([(a + b) / 2 for a, b in zip(low, high)])
    half_wide = math.tan(math.radians(VIEW) / 2)
    distance, back = camera_distance(corners, centre, to_scene(direction), half_wide, half_wide * HEIGHT / WIDTH)
    # Fusion keeps the size of the view when the angle changes by moving the camera, so the angle goes in first.
    camera = viewport.camera
    camera.isSmoothTransition = False
    camera.cameraType = adsk.core.CameraTypes.PerspectiveCameraType
    camera.perspectiveAngle = 2 * math.atan(half_wide * viewport.height * VIEW_HEIGHT / viewport.width)
    viewport.camera = camera
    adsk.doEvents()
    camera = viewport.camera
    camera.isSmoothTransition = False
    camera.eye = adsk.core.Point3D.create(*[(c + distance * v) * CM for c, v in zip(centre, back)])
    camera.target = adsk.core.Point3D.create(*[v * CM for v in centre])
    camera.upVector = adsk.core.Vector3D.create(0, 1, 0)
    viewport.camera = camera
    adsk.doEvents()
    placed = viewport.camera
    print("camera", round(distance), "mm back, placed at", round(placed.eye.distanceTo(placed.target) / CM),
          "angle", round(placed.perspectiveAngle, 4))
    if os.path.exists(path):
        os.remove(path)
    future = rendering.startLocalRender(path, viewport.camera)
    started = time.time()
    while time.time() - started < SECONDS:
        adsk.doEvents()
        if future.renderState == adsk.fusion.LocalRenderStates.FinishedLocalRenderState:
            break
        if future.renderState == adsk.fusion.LocalRenderStates.FailedLocalRenderState:
            print("render failed", path)
            break
        time.sleep(0.5)
    print(os.path.basename(path), "state", future.renderState, "seconds", round(time.time() - started),
          "saved" if os.path.exists(path) else "NOT saved")


def run():
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    app.userInterface.workspaces.itemById("FusionRenderEnvironment").activate()
    adsk.doEvents()
    manager = design.renderManager
    scene = manager.sceneSettings
    set_all(scene, {
        "backgroundType": adsk.fusion.RenderSceneBackgroundTypes.SolidColorRenderSceneBackgroundType,
        "backgroundSolidColor": adsk.core.Color.create(BACKDROP[0], BACKDROP[1], BACKDROP[2], 255),
        "isGroundDisplayed": True,      # the ground catches the shadow under the case
        "isGroundFlattened": True,
        "isGroundReflections": False,
        "cameraExposure": 9.6,          # a lower number is brighter
        "lightAngle": LIGHT,
    })
    rendering = manager.rendering
    set_all(rendering, {
        "aspectRatio": adsk.fusion.RenderAspectRatios.CustomRenderAspectRatio,
        "resolution": adsk.fusion.RenderResolutions.CustomRenderResolution,
        "resolutionWidth": WIDTH,
        "resolutionHeight": HEIGHT,
        "isBackgroundTransparent": False,
        "renderQuality": 60,
    })
    # The box around both parts, measured from the model before it is turned.
    box = design.rootComponent.boundingBox
    low = [v / CM for v in (box.minPoint.x, box.minPoint.y, box.minPoint.z)]
    high = [v / CM for v in (box.maxPoint.x, box.maxPoint.y, box.maxPoint.z)]
    print("case", [round(b - a, 2) for a, b in zip(low, high)], "mm")
    viewport = app.activeViewport
    homes = turn_for_pictures(design)
    try:
        render_one(rendering, viewport, low, high, (0.62, -0.62, 0.48), os.path.join(PICTURES, "xdtgc_case_render.png"))
        render_one(rendering, viewport, low, high, (-0.55, -0.70, 0.42), os.path.join(PICTURES, "xdtgc_case_render_fins.png"))
        render_one(rendering, viewport, low, high, (0.0, -0.45, 0.89), os.path.join(PICTURES, "xdtgc_case_render_top.png"))
    finally:
        put_back(homes)

    # The lid raised, to show how the two parts go together.
    homes = turn_for_pictures(design, lift=LIFT)
    try:
        render_one(rendering, viewport, low, (high[0], high[1], high[2] + LIFT), (0.62, -0.62, 0.40),
                   os.path.join(PICTURES, "xdtgc_case_render_open.png"))
    finally:
        put_back(homes)
    print("Rendered")


try:
    run()
except Exception:
    import traceback
    print(traceback.format_exc())
