#!/usr/bin/env python3
"""Usage: "<KiCad>/bin/python.exe" scripts/pcb_place.py NETLIST.net BOARD.kicad_pcb

Builds the backpack board from a KiCad netlist: 4 copper layers, outline, footprints,
net assignments and placement. No tracks. Replaces the board file, so close unsaved work first.
"""
import os
import re
import sys

import pcbnew

ROW_SPACING = 20.32  # Measured from Sipeed 3D model v3921 (holes at y=1.14 and 21.46). Check on the real board.
PITCH = 2.54  # Source: Sipeed dimension drawing and datasheet
BOARD_W = 54.04  # Same length as the Tang Nano 20K (Sipeed dimension drawing)
BOARD_H = 25.0  # 2.45 mm wider than the Tang so the socket pads clear the board edge
X0, Y0 = 100.0, 100.0
MID_Y = Y0 + BOARD_H / 2
ROW_TOP = MID_Y - ROW_SPACING / 2
ROW_BOTTOM = MID_Y + ROW_SPACING / 2
HEADER_X = X0 + (BOARD_W - 19 * PITCH) / 2

BACK_SIDE = {"J2", "J3"}

# Reference: (x, y, rotation in degrees). Rows run along the long edge of the board.
# Top view with USB on the left: Tang J5 is the top row, Tang J6 the bottom row, and pin 1 of both
# is at the USB end. Source: Sipeed pin label image (tang_nano_20k_pinlabel.png).
PLACE = {
    "J1": (X0 + 3.6, MID_Y + 0.05, 270),  # Its 0.5 mm pads line up with U1 pins 7 and 8
    "J2": (HEADER_X, ROW_TOP, 90),
    "J3": (HEADER_X, ROW_BOTTOM, 90),
    "U1": (X0 + 27.05, MID_Y + 0.05, 0),  # 0.05 offset puts its pads on the router's 0.1 mm grid
    "D1": (X0 + 12, MID_Y - 0.45, 270),  # USB pair runs straight between its pads
    # Crystal by pins 2 and 3
    "Y1": (X0 + 15.5, MID_Y - 6.3, 0),
    "C14": (X0 + 12.1, MID_Y - 6.3, 90),
    "C15": (X0 + 18.9, MID_Y - 6.3, 90),
    # Left side of U1: analogue supplies and reference, each by its own pin
    "C9": (X0 + 19.0, MID_Y - 2.3, 180),  # VPHY, pin 4
    "FB2": (X0 + 15.8, MID_Y - 2.6, 0),
    "R1": (X0 + 18.6, MID_Y - 1.3, 180),  # REF, pin 6. Pad 1 faces the pin so the track is short and direct
    "C8": (X0 + 19.0, MID_Y + 1.0, 180),  # VPLL, pin 9
    "FB1": (X0 + 16.2, MID_Y + 1.2, 0),
    "C2": (X0 + 19.0, MID_Y + 2.2, 180),  # 1V8, pin 12
    "C17": (X0 + 19.6, MID_Y + 4.3, 90),  # VPLL bulk, after FB1
    "C18": (X0 + 18.8, MID_Y - 3.6, 0),  # VPHY bulk, after FB2
    "R9": (X0 + 17.6, MID_Y + 4.3, 90),  # RESET# pull-up, pin 14
    # Top of U1
    "C1": (X0 + 23.3, MID_Y - 7.55, 0),  # 1V8, pin 64
    "C4": (X0 + 27.3, MID_Y - 7.55, 0),  # 3V3, pin 56
    "C5": (X0 + 29.9, MID_Y - 7.55, 0),  # 3V3, pin 50
    "C11": (X0 + 32.4, MID_Y - 7.55, 0),  # 1V8 regulator output, pin 49
    # Bottom of U1
    "C6": (X0 + 24.8, MID_Y + 7.55, 0),  # 3V3, pin 20
    "C7": (X0 + 31.5, MID_Y + 7.55, 0),  # 3V3, pin 31
    # Right of U1
    "C10": (X0 + 34.3, MID_Y - 0.75, 90),  # 3V3, pin 42
    "C3": (X0 + 34.3, MID_Y + 1.75, 90),  # 1V8, pin 37
    # EEPROM
    "U3": (X0 + 40.5, MID_Y - 4, 0),
    "C16": (X0 + 40.5, MID_Y - 7.55, 0),
    "R4": (X0 + 35.5, MID_Y - 2.2, 90),
    "R5": (X0 + 37.0, MID_Y - 0.2, 0),
    "R6": (X0 + 39.5, MID_Y - 0.2, 0),
    "R7": (X0 + 42.5, MID_Y - 0.2, 0),
    "R8": (X0 + 35.5, MID_Y + 3.2, 90),
    # Power: fuse by the USB connector, diode by Tang 5 V pin (J2-1), regulator on the right
    "F1": (X0 + 12.5, MID_Y + 6.8, 0),
    "D2": (X0 + 7.5, MID_Y - 7.2, 180),
    "R2": (X0 + 10.0, MID_Y + 4.5, 0),
    "R3": (X0 + 10.0, MID_Y - 4.5, 0),
    "U2": (X0 + 45, MID_Y + 4.6, 0),
    "C12": (X0 + 38.2, MID_Y + 5, 0),
    "C13": (X0 + 49.5, MID_Y - 1.5, 90),
}


SILK_LABELS = {"J1", "U2"}


def parse(text):
    """Reads an s-expression into nested lists of strings."""
    tokens = re.findall(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+', text)
    stack, cur = [], []
    for tok in tokens:
        if tok == "(":
            stack.append(cur)
            cur = []
        elif tok == ")":
            done = cur
            cur = stack.pop()
            cur.append(done)
        else:
            cur.append(tok[1:-1] if tok.startswith('"') else tok)
    return cur[0]


def child(node, name):
    return next((c for c in node if isinstance(c, list) and c and c[0] == name), None)


def children(node, name):
    return [c for c in node if isinstance(c, list) and c and c[0] == name]


def mm(x, y):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))


def add_outline(board):
    """Rounded corners use the same 2.54 mm radius as the Tang Nano 20K."""
    x1, y1, x2, y2 = X0, Y0, X0 + BOARD_W, Y0 + BOARD_H
    r = 2.54
    lines = [(x1 + r, y1, x2 - r, y1), (x2, y1 + r, x2, y2 - r), (x2 - r, y2, x1 + r, y2), (x1, y2 - r, x1, y1 + r)]
    arcs = [((x1 + r, y1 + r), (x1, y1 + r), (x1 + r, y1)), ((x2 - r, y1 + r), (x2 - r, y1), (x2, y1 + r)),
            ((x2 - r, y2 - r), (x2, y2 - r), (x2 - r, y2)), ((x1 + r, y2 - r), (x1 + r, y2), (x1, y2 - r))]
    for a, b, c, d in lines:
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(mm(a, b))
        s.SetEnd(mm(c, d))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(pcbnew.FromMM(0.05))
        board.Add(s)
    for centre, start, end in arcs:
        s = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_ARC)
        s.SetCenter(mm(*centre))
        s.SetStart(mm(*start))
        s.SetEnd(mm(*end))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(pcbnew.FromMM(0.05))
        board.Add(s)


def main():
    netlist = parse(open(sys.argv[1], encoding="utf8").read())
    board_path = sys.argv[2]
    lib_root = os.path.join(os.path.dirname(os.path.dirname(sys.executable)), "share", "kicad", "footprints")

    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)
    add_outline(board)

    nets = {}
    pad_net = {}
    for net in children(child(netlist, "nets"), "net"):
        name = child(net, "name")[1]
        info = pcbnew.NETINFO_ITEM(board, name)
        board.Add(info)
        nets[name] = info
        for node in children(net, "node"):
            pad_net[(child(node, "ref")[1], child(node, "pin")[1])] = info

    missing = []
    for comp in children(child(netlist, "components"), "comp"):
        ref = child(comp, "ref")[1]
        fp_field = child(comp, "footprint")
        if fp_field is None:
            if not ref.startswith("#"):
                missing.append(ref + " has no footprint")
            continue
        lib, name = fp_field[1].split(":")
        fp = pcbnew.FootprintLoad(os.path.join(lib_root, lib + ".pretty"), name)
        if fp is None:
            sys.exit(f"footprint not found: {fp_field[1]}")
        fp.SetFPID(pcbnew.LIB_ID(lib, name))  # FootprintLoad leaves out the library name
        fp.SetReference(ref)
        fp.Value().SetVisible(False)
        fp.Reference().SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(0.7), pcbnew.FromMM(0.7)))
        fp.Reference().SetTextThickness(pcbnew.FromMM(0.1))
        fp.Reference().SetVisible(ref in SILK_LABELS)  # the small parts are too close together for a label each
        fp.SetValue(child(comp, "value")[1])
        board.Add(fp)
        if ref in PLACE:
            x, y, rot = PLACE[ref]
        else:
            missing.append(ref + " has no placement")
            x, y, rot = X0 + BOARD_W + 5, Y0 + len(missing) * 4, 0
        fp.SetPosition(mm(x, y))
        fp.SetOrientationDegrees(rot)
        if ref in BACK_SIDE:
            # Sockets sit under the board and plug onto the Tang's pins. Flipping mirrors the
            # footprint, so keep pin 1 at the USB end as seen from the top.
            fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
            first, last = (next(p for p in fp.Pads() if p.GetNumber() == n).GetPosition().x for n in ("1", "20"))
            if first > last:
                fp.SetOrientationDegrees(fp.GetOrientationDegrees() + 180)
                dx = fp.GetPosition().x - next(p for p in fp.Pads() if p.GetNumber() == "1").GetPosition().x
                fp.SetPosition(pcbnew.VECTOR2I(fp.GetPosition().x + dx + pcbnew.FromMM(x) - fp.GetPosition().x, fp.GetPosition().y))
        for pad in fp.Pads():
            if ref == "J1" and pad.GetNumber() == "SH":
                pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)  # Shell tabs: solid to ground
            info = pad_net.get((ref, pad.GetNumber()))
            if info is not None:
                pad.SetNet(info)

    pcbnew.SaveBoard(board_path, board)
    print("footprints", len(board.GetFootprints()), "nets", len(nets), "layers", board.GetCopperLayerCount())
    for line in missing:
        print("WARNING:", line)


if __name__ == "__main__":
    main()
