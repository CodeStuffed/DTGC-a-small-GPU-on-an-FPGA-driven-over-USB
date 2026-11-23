"""Usage, in Fusion's Text Commands box with Py selected:
    exec(open(r"C:\\Users\\User\\Documents\\tinygpu\\scripts\\case_fusion.py").read())

Builds the sculpted xDTGC case as real solids inside Autodesk Fusion, using the board sizes and connector holes in
pcb/case/case_boxes.json (from scripts/case_stl.py, so change sizes there). Saves a STEP file, two STL files and
preview pictures. The space inside and the connector holes are the same as the plain case. Not yet test-fitted.

The shape (third version): a block with round corners. Each long side has one stack of thin fins whose lower edge
climbs from one end to the other, like a heatsink cut on a slant. The lid is flat on top so it can be printed top
down with no supports. It has a honeycomb of vent holes that shrink toward the end with the name on it, and a thin
shadow line where it meets the tray, which hides small errors in the fit.
"""
import json
import math
import os

import adsk.core
import adsk.fusion

CASE_FOLDER = r"C:\Users\User\Documents\tinygpu\pcb\case"
PICTURES = r"C:\Users\User\Documents\tinygpu\docs\images"
DOCUMENT = "xDTGC case v3"
CM = 0.1             # Fusion's scripts measure in cm

SIDE = 2.6           # extra thickness on each long side, where the fins are, mm. The ends stay thin so plugs can seat
ROUND = 4.0          # radius of the corners seen from above. More than 4.2 would thin the wall at the corners
PLINTH_HEIGHT, PLINTH_INSET = 1.5, 1.2     # sloped edge under the tray
FIN_PITCH, FIN_SLOT, FIN_DEPTH = 1.7, 0.9, 2.1     # leaves 0.8 mm fins, two lines of a 0.4 mm nozzle
FIN_END = 7.0        # solid part at each end of the fin stack
FIN_BOTTOM, FIN_TOP = 3.0, 3.6     # the tallest slot starts this far above the floor and all end this far below the lid
FIN_SHORTEST = 3.5   # height of the last, shortest slot

LID_EDGE, LID_SLOPE, LID_INSET = 1.2, 1.8, 1.4     # the lid's straight edge, then its slope
LID_ROOF = 2.0       # thickness of the lid's top above the space inside
SEAM = 0.5           # height and depth of the shadow line around the bottom of the lid
HEX_PITCH = 3.4      # distance between the centres of neighbouring vent holes
HEX_LARGE, HEX_SMALL = 2.6, 1.2     # width of a hole across its flat sides, at the big end and at the small end
HEX_ROWS = 7
HEX_FIRST, HEX_LAST = 6.5, 36.5     # where the holes start and stop along the lid
NAME_HEIGHT = 4.2    # letter height of the name


def frame(size_x, size_y, inset):
    """The outline seen from above as (x0, y0, x1, y1, corner radius). y runs from -SIDE to size_y + SIDE."""
    return (inset, -SIDE + inset, size_x - inset, size_y + SIDE - inset, ROUND - inset)


class Part:
    def __init__(self, root, name):
        self.occurrence = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        self.component = self.occurrence.component
        self.component.name = name
        self.name = name
        self.body = None

    def plane(self, z):
        planes = self.component.constructionPlanes
        plane_input = planes.createInput()
        plane_input.setByOffset(self.component.xYConstructionPlane, adsk.core.ValueInput.createByReal(z * CM))
        plane = planes.add(plane_input)
        plane.isLightBulbOn = False
        return plane

    def polygon(self, sketch, points):
        lines = sketch.sketchCurves.sketchLines
        corners = [adsk.core.Point3D.create(x * CM, y * CM, 0) for x, y in points]
        for a, b in zip(corners, corners[1:] + corners[:1]):
            lines.addByTwoPoints(a, b)

    def round_rectangle(self, sketch, outline):
        """A rectangle with round corners, drawn as four lines whose corners are then filleted so that it is closed."""
        x0, y0, x1, y1, radius = outline
        lines = sketch.sketchCurves.sketchLines
        corners = [adsk.core.Point3D.create(x * CM, y * CM, 0) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        sides = [lines.addByTwoPoints(a, b) for a, b in zip(corners, corners[1:] + corners[:1])]
        if radius > 0:
            for first, second in zip(sides, sides[1:] + sides[:1]):
                sketch.sketchCurves.sketchArcs.addFillet(first, first.endSketchPoint.geometry,
                                                         second, second.startSketchPoint.geometry, radius * CM)

    def outline_sketch(self, outline, z):
        sketch = self.component.sketches.add(self.plane(z))
        self.round_rectangle(sketch, outline)
        return sketch

    def loft(self, lower, lower_z, upper, upper_z):
        """Makes the part's first solid: a slope from one outline to another."""
        lofts = self.component.features.loftFeatures
        loft_input = lofts.createInput(adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        loft_input.loftSections.add(self.outline_sketch(lower, lower_z).profiles.item(0))
        loft_input.loftSections.add(self.outline_sketch(upper, upper_z).profiles.item(0))
        self.body = lofts.add(loft_input).bodies.item(0)
        self.body.name = self.name

    def extrude(self, profiles, distance, operation):
        extrusions = self.component.features.extrudeFeatures
        extrude_input = extrusions.createInput(profiles, operation)
        extrude_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(distance * CM))
        extrude_input.participantBodies = [self.body]
        return extrusions.add(extrude_input)

    def add_slab(self, outline, z0, z1):
        sketch = self.outline_sketch(outline, z0)
        self.extrude(sketch.profiles.item(0), z1 - z0, adsk.fusion.FeatureOperations.JoinFeatureOperation)

    def cut_ring(self, outer, inner, z0, z1):
        """Removes the strip between two outlines, one inside the other."""
        sketch = self.component.sketches.add(self.plane(z0))
        self.round_rectangle(sketch, outer)
        self.round_rectangle(sketch, inner)
        rings = [profile for profile in sketch.profiles if profile.profileLoops.count == 2]
        self.extrude(rings[0], z1 - z0, adsk.fusion.FeatureOperations.CutFeatureOperation)

    def box(self, box, operation):
        x0, y0, z0, x1, y1, z1 = box
        sketch = self.component.sketches.add(self.plane(z0))
        self.polygon(sketch, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
        self.extrude(sketch.profiles.item(0), z1 - z0, operation)

    def cut_box(self, box):
        self.box(box, adsk.fusion.FeatureOperations.CutFeatureOperation)

    def join_box(self, box):
        self.box(box, adsk.fusion.FeatureOperations.JoinFeatureOperation)


def all_profiles(sketch):
    profiles = adsk.core.ObjectCollection.create()
    for profile in sketch.profiles:
        profiles.add(profile)
    return profiles


def side_sketch(part, y_plane):
    planes = part.component.constructionPlanes
    plane_input = planes.createInput()
    plane_input.setByOffset(part.component.xZConstructionPlane, adsk.core.ValueInput.createByReal(y_plane * CM))
    plane = planes.add(plane_input)
    plane.isLightBulbOn = False
    return part.component.sketches.add(plane)


def rectangle_on_side(sketch, y_plane, x0, z0, x1, z1):
    a = sketch.modelToSketchSpace(adsk.core.Point3D.create(x0 * CM, y_plane * CM, z0 * CM))
    b = sketch.modelToSketchSpace(adsk.core.Point3D.create(x1 * CM, y_plane * CM, z1 * CM))
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(a, b)


def cut_inward(part, sketch, depth, inward_y):
    """Cuts from a long side's outer face toward the middle. Only as deep as the extra thickness, so the wall stays whole."""
    normal = sketch.transform.getAsCoordinateSystem()[3]
    distance = depth * inward_y * (1 if normal.y > 0 else -1)
    part.extrude(all_profiles(sketch), distance, adsk.fusion.FeatureOperations.CutFeatureOperation)


def cut_fins(part, y_plane, inward_y, size_x, height):
    """One stack of slots. All end at the same height, and each starts a little higher than the one before."""
    sketch = side_sketch(part, y_plane)
    last = int((size_x - 2 * FIN_END) / FIN_PITCH)
    first_x = (size_x - last * FIN_PITCH) / 2
    top = height - FIN_TOP
    for i in range(last + 1):
        x = first_x + i * FIN_PITCH
        bottom = FIN_BOTTOM + (top - FIN_SHORTEST - FIN_BOTTOM) * i / last
        rectangle_on_side(sketch, y_plane, x - FIN_SLOT / 2, bottom, x + FIN_SLOT / 2, top)
    cut_inward(part, sketch, FIN_DEPTH, inward_y)
    return last + 1


def build_tray(root, shapes):
    size_x, size_y, height = shapes["outside_x"], shapes["outside_y"], shapes["tray_z"]
    part = Part(root, "xDTGC tray")
    full = frame(size_x, size_y, 0)
    part.loft(frame(size_x, size_y, PLINTH_INSET), -PLINTH_HEIGHT, full, 0)
    part.add_slab(full, 0, height)
    for box in shapes["tray"]["remove"]:
        part.cut_box(box)
    for box in shapes["tray"]["add_after"]:
        part.join_box(box)
    count = cut_fins(part, -SIDE, 1, size_x, height)
    cut_fins(part, size_y + SIDE, -1, size_x, height)
    print("fin slots on each side", count)
    return part


def honeycomb(part, sketch, centre_y):
    """Six-sided holes on a triangular grid, so the strip between any two neighbours has the same width all along."""
    count = 0
    row_pitch = HEX_PITCH * math.sin(math.radians(60))
    for row in range(HEX_ROWS):
        y = centre_y + (row - (HEX_ROWS - 1) / 2) * row_pitch
        x = HEX_FIRST + (HEX_PITCH / 2 if row % 2 else 0)
        while x <= HEX_LAST:
            across = HEX_LARGE - (HEX_LARGE - HEX_SMALL) * (x - HEX_FIRST) / (HEX_LAST - HEX_FIRST)
            radius = across / math.sqrt(3)      # centre to corner
            part.polygon(sketch, [(x + radius * math.sin(math.radians(60 * k)), y + radius * math.cos(math.radians(60 * k)))
                                  for k in range(6)])
            count += 1
            x += HEX_PITCH
    return count


def build_lid(root, shapes):
    size_x, size_y, mate = shapes["outside_x"], shapes["outside_y"], shapes["tray_z"]
    wall, fit, lip = shapes["wall"], shapes["fit"], shapes["lip"]
    part = Part(root, "xDTGC lid")
    full = frame(size_x, size_y, 0)
    edge_top = mate + LID_EDGE
    top = edge_top + LID_SLOPE
    part.loft(full, edge_top, frame(size_x, size_y, LID_INSET), top)
    part.add_slab(full, mate, edge_top)
    outer = wall + fit
    part.join_box((outer, outer, mate - lip, size_x - outer, size_y - outer, mate))
    inner = outer + wall
    ceiling = top - LID_ROOF
    part.cut_box((inner, inner, mate - lip, size_x - inner, size_y - inner, ceiling))
    part.cut_ring(full, frame(size_x, size_y, SEAM), mate, mate + SEAM)

    centre_y = size_y / 2
    sketch = part.component.sketches.add(part.plane(ceiling))
    count = honeycomb(part, sketch, centre_y)
    part.extrude(all_profiles(sketch), LID_ROOF, adsk.fusion.FeatureOperations.CutFeatureOperation)

    # The name, pressed into the solid end of the lid.
    sketch = part.component.sketches.add(part.plane(top))
    texts = sketch.sketchTexts
    text_input = texts.createInput2("xDTGC", NAME_HEIGHT * CM)
    x0, x1 = HEX_LAST + 1.0, size_x - inner - 0.5
    text_input.setAsMultiLine(adsk.core.Point3D.create(x0 * CM, (centre_y - NAME_HEIGHT) * CM, 0),
                              adsk.core.Point3D.create(x1 * CM, (centre_y + NAME_HEIGHT) * CM, 0),
                              adsk.core.HorizontalAlignments.CenterHorizontalAlignment,
                              adsk.core.VerticalAlignments.MiddleVerticalAlignment, 0)
    text_input.fontName = "Arial"
    try:
        text_input.textStyle = adsk.fusion.TextStyles.TextStyleBold
    except Exception:
        pass
    text = texts.add(text_input)
    extrusions = part.component.features.extrudeFeatures
    extrude_input = extrusions.createInput(text, adsk.fusion.FeatureOperations.CutFeatureOperation)
    extrude_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-0.4 * CM))
    extrude_input.participantBodies = [part.body]
    extrusions.add(extrude_input)
    print("vent holes", count)
    return part


def paint(app, design, part, name, colour):
    """Screen colour only. A print comes out in whatever colour the filament is."""
    library = app.materialLibraries.itemByName("Fusion Appearance Library")
    if library is None:
        return
    for base in ("Plastic - Matte (Black)", "Plastic - Matte (White)", "Plastic - Matte (Gray)"):
        source = library.appearances.itemByName(base)
        if source is None:
            continue
        look = design.appearances.itemByName(name) or design.appearances.addByCopy(source, name)
        for i in range(look.appearanceProperties.count):
            item = adsk.core.ColorProperty.cast(look.appearanceProperties.item(i))
            if item is not None and item.name == "Color":
                item.value = adsk.core.Color.create(colour[0], colour[1], colour[2], 255)
        part.body.appearance = look
        print(part.name, "look", name, "from", base)
        return
    print(part.name, "kept the default look")


def picture(app, eye, target, up, path):
    camera = app.activeViewport.camera
    camera.isSmoothTransition = False
    camera.eye = adsk.core.Point3D.create(*[v * CM for v in eye])
    camera.target = adsk.core.Point3D.create(*[v * CM for v in target])
    camera.upVector = adsk.core.Vector3D.create(*up)
    app.activeViewport.camera = camera
    app.activeViewport.fit()
    adsk.doEvents()
    app.activeViewport.refresh()
    app.activeViewport.saveAsImageFile(path, 1600, 1100)


def run():
    app = adsk.core.Application.get()
    with open(os.path.join(CASE_FOLDER, "case_boxes.json")) as f:
        shapes = json.load(f)
    # An earlier run of this script leaves its unsaved document open. Close those, and nothing else.
    for old in [d for d in app.documents if d.name.startswith(DOCUMENT) and not d.isSaved]:
        old.close(False)
    document = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    document.name = DOCUMENT
    design = adsk.fusion.Design.cast(app.activeProduct)
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    root = design.rootComponent
    tray = build_tray(root, shapes)
    lid = build_lid(root, shapes)
    paint(app, design, tray, "xDTGC graphite", (88, 93, 104))
    paint(app, design, lid, "xDTGC bone", (233, 230, 222))
    for part in (tray, lid):
        part.component.isSketchFolderLightBulbOn = False
        part.component.isConstructionFolderLightBulbOn = False
    root.isOriginFolderLightBulbOn = False

    manager = design.exportManager
    manager.execute(manager.createSTEPExportOptions(os.path.join(CASE_FOLDER, "xdtgc_case_sculpted.step")))
    for part, name in ((tray, "tray"), (lid, "lid")):
        options = manager.createSTLExportOptions(part.body, os.path.join(CASE_FOLDER, f"sculpted_{name}_raw.stl"))
        options.isBinaryFormat = True
        options.sendToPrintUtility = False
        options.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
        manager.execute(options)

    size_x, size_y, height = shapes["outside_x"], shapes["outside_y"], shapes["tray_z"]
    centre = (size_x / 2, size_y / 2, height / 2)
    up = (0, 0, 1)
    picture(app, (size_x + 90, -90, height + 70), centre, up, os.path.join(PICTURES, "xdtgc_case_sculpted.png"))
    picture(app, (centre[0], centre[1], 220), centre, (0, 1, 0), os.path.join(PICTURES, "xdtgc_case_sculpted_top.png"))
    picture(app, (centre[0] - 40, centre[1] - 150, height + 20), centre, up, os.path.join(PICTURES, "xdtgc_case_sculpted_side.png"))
    for part in (tray, lid):
        print(part.name, "volume", round(part.body.volume * 1000, 1), "mm3, faces", part.body.faces.count)
    print("Built the case")


try:
    run()
except Exception:
    import traceback
    print(traceback.format_exc())
