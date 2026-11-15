#!/usr/bin/env python3
"""Usage: "<KiCad>/bin/python.exe" scripts/pcb_route.py BOARD.kicad_pcb [SEED]

Routes the backpack board made by pcb_place.py. Layers: F.Cu and B.Cu signals, In1.Cu GND plane,
In2.Cu +3V3 plane. Grid maze router (A*) with rip-up and retry. Removes old tracks and zones first.
Passing DRC only means the rules hold: the USB pair, clock and power still need human review.
"""
import heapq
import json
import math
import random
import sys

import numpy as np
import pcbnew

GRID = 0.1  # mm
CLEARANCE = 0.15  # what the router aims for; the board rule is 0.127 so it has margin
TRACK = 0.15
VIA_D, VIA_DRILL = 0.5, 0.2  # 0.15 mm copper ring. VERIFY against the fab's 4-layer limits
VIA_COST = 12
PLANES = {"/GND": pcbnew.In1_Cu, "/+3V3": pcbnew.In2_Cu}
WIDTH = {"/VBUS_IN": 0.5, "/VBUS": 0.5, "/TANG_5V": 0.5, "/VPHY": 0.25, "/VPLL": 0.25, "/+1V8": 0.2,
         "/USB_DP": 0.25, "/USB_DN": 0.25}  # with a 0.25 gap, about 93 ohms on PCBWay's stack: docs/pcb-layout-review.md
FIRST = ["/USB_DP", "/USB_DN"]  # Laid out by hand in route_usb
USB_NECK = 0.2  # Narrower by the connector, where the bridge vias sit between the rows. Width up to neck_end
neck_end = [0.0]
POWER = ["/VBUS_IN", "/VBUS", "/TANG_5V"]  # Kept out from under U1 so the data bus can cross there
# These pins are on the wrong side of U1 for their header, so each drops through a via under the
# chip and crosses on B.Cu.
FAN_IN = ["/FIFO_D%d" % i for i in range(8)] + ["/+1V8", "/EECS", "/EECLK", "/EEDATA"]
EARLY = ["/+1V8", "/EECS", "/EECLK", "/EEDATA", "/EEDO"]
BODY = 4.5  # half width of the area under U1 kept for plane vias, mm
LAYERS = [pcbnew.F_Cu, pcbnew.B_Cu]
MOVES = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
         (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)]
BLOCKED = -2
FREE = -1


def to_mm(v):
    return pcbnew.ToMM(v)


class Grid:
    def __init__(self, board):
        box = board.GetBoardEdgesBoundingBox()
        # Outline line width pushes the box out slightly, so snap back to the grid
        self.x0 = round(to_mm(box.GetLeft()) / GRID) * GRID
        self.y0 = round(to_mm(box.GetTop()) / GRID) * GRID
        self.w = int(round(to_mm(box.GetWidth()) / GRID)) + 1
        self.h = int(round(to_mm(box.GetHeight()) / GRID)) + 1
        self.board_w, self.board_h = to_mm(box.GetWidth()), to_mm(box.GetHeight())
        self.owner = np.full((2, self.h, self.w), FREE, dtype=np.int32)

    def cell(self, x, y):
        return int(round((x - self.x0) / GRID)), int(round((y - self.y0) / GRID))

    def pos(self, cx, cy):
        return self.x0 + cx * GRID, self.y0 + cy * GRID

    def claim(self, layer, mask_slice, mask, net):
        view = self.owner[layer][mask_slice]
        conflict = mask & (view != FREE) & (view != net)
        view[mask & (view == FREE)] = net
        view[conflict] = BLOCKED

    def paint_rect(self, layer, x1, y1, x2, y2, grow, net):
        """Marks cells where a track centre would be too close to a rectangle."""
        c1 = self.cell(x1 - grow, y1 - grow)
        c2 = self.cell(x2 + grow, y2 + grow)
        xs = np.arange(max(c1[0] - 1, 0), min(c2[0] + 2, self.w))
        ys = np.arange(max(c1[1] - 1, 0), min(c2[1] + 2, self.h))
        if len(xs) == 0 or len(ys) == 0:
            return
        px = self.x0 + xs * GRID
        py = self.y0 + ys * GRID
        dx = np.maximum(np.maximum(x1 - px, px - x2), 0)
        dy = np.maximum(np.maximum(y1 - py, py - y2), 0)
        mask = (dy[:, None] ** 2 + dx[None, :] ** 2) < (grow - 1e-6) ** 2
        self.claim(layer, (slice(ys[0], ys[-1] + 1), slice(xs[0], xs[-1] + 1)), mask, net)

    def paint_edge(self, margin):
        m = int(math.ceil(margin / GRID))
        self.owner[:, :m, :] = BLOCKED
        self.owner[:, -m:, :] = BLOCKED
        self.owner[:, :, :m] = BLOCKED
        self.owner[:, :, -m:] = BLOCKED
        # Rounded corners
        r = 2.54 + margin
        corners = [(2.54, 2.54), (self.board_w - 2.54, 2.54),
                   (2.54, self.board_h - 2.54), (self.board_w - 2.54, self.board_h - 2.54)]
        ys, xs = np.mgrid[0:self.h, 0:self.w]
        px, py = xs * GRID, ys * GRID
        for cx, cy in corners:
            in_corner = (np.abs(px - self.board_w / 2) > self.board_w / 2 - 2.54) & (np.abs(py - self.board_h / 2) > self.board_h / 2 - 2.54)
            near = (np.sign(px - self.board_w / 2) == np.sign(cx - self.board_w / 2)) & (np.sign(py - self.board_h / 2) == np.sign(cy - self.board_h / 2))
            outside = (px - cx) ** 2 + (py - cy) ** 2 > (2.54 - margin) ** 2
            self.owner[:, in_corner & near & outside] = BLOCKED


class Router:
    def __init__(self, board):
        self.board = board
        self.pads = []
        self.net_ids = {}
        for fp in board.GetFootprints():
            for pad in fp.Pads():
                pos = pad.GetPosition()
                box = pad.GetBoundingBox()
                through = pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
                hole_only = pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH
                name = pad.GetNetname()
                self.pads.append(dict(ref=fp.GetReference(), num=pad.GetNumber(), net=name,
                                      x=to_mm(pos.x), y=to_mm(pos.y),
                                      x1=to_mm(box.GetLeft()), y1=to_mm(box.GetTop()),
                                      x2=to_mm(box.GetRight()), y2=to_mm(box.GetBottom()),
                                      layers=[0, 1] if through or hole_only else [0 if pad.IsOnLayer(pcbnew.F_Cu) else 1],
                                      round=through or hole_only, npth=hole_only))
                self.net_ids.setdefault(name, len(self.net_ids))
        self.routes = {}
        self.fan_via = {}
        pos = next(f for f in board.GetFootprints() if f.GetReference() == "U1").GetPosition()
        self.u1 = (to_mm(pos.x), to_mm(pos.y))

    def close_body(self):
        """Stops later F.Cu tracks wandering under U1, where they would box in its pins."""
        g = self.g
        c1 = g.cell(self.u1[0] - BODY - 0.4, self.u1[1] - BODY - 0.4)
        c2 = g.cell(self.u1[0] + BODY + 0.4, self.u1[1] + BODY + 0.4)
        view = g.owner[0, c1[1]:c2[1], c1[0]:c2[0]]
        view[view == FREE] = BLOCKED

    def close_back_under_u1(self, closing):
        g = self.g
        c1 = g.cell(self.u1[0] - 8, self.u1[1] - 8)
        c2 = g.cell(self.u1[0] + 8, self.u1[1] + 8)
        view = g.owner[1, c1[1]:c2[1], c1[0]:c2[0]]
        if closing:
            self.saved_back = view.copy()
            view[view == FREE] = BLOCKED
        else:
            view[:] = self.saved_back

    def nid(self, name):
        return self.net_ids[name]

    def rebuild(self):
        g = Grid(self.board)
        g.paint_edge(0.35)
        for p in self.pads:
            net = BLOCKED if p["npth"] or not p["net"] else self.nid(p["net"])
            for layer in p["layers"]:
                # Bare holes have a larger rule (0.2 mm) than copper
                grow = CLEARANCE + TRACK / 2 + (0.1 if p["npth"] else 0)
                g.paint_rect(layer, p["x1"], p["y1"], p["x2"], p["y2"], grow, net)
        self.g = g
        # A via in a surface pad can draw solder away from the joint, so the search keeps vias out of them.
        self.no_via = set()
        margin = VIA_D / 2
        for p in self.pads:
            if not p["npth"] and len(p["layers"]) == 1:
                c1 = g.cell(p["x1"] - margin, p["y1"] - margin)
                c2 = g.cell(p["x2"] + margin, p["y2"] + margin)
                self.no_via.update((cx, cy) for cy in range(c1[1], c2[1] + 1) for cx in range(c1[0], c2[0] + 1))
        for name, items in self.routes.items():
            for item in items:
                self.paint_item(item, self.nid(name), WIDTH.get(name, TRACK))

    def paint_item(self, item, net, width):
        g = self.g
        if item[0] == "via":
            _, x, y = item
            for layer in (0, 1):
                grow = VIA_D / 2 + CLEARANCE + TRACK / 2
                g.paint_rect(layer, x, y, x, y, grow, net)
        else:
            _, layer, x1, y1, x2, y2 = item
            grow = width / 2 + CLEARANCE + TRACK / 2
            steps = max(int(max(abs(x2 - x1), abs(y2 - y1)) / GRID), 1)
            for i in range(steps + 1):
                t = i / steps
                x, y = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
                g.paint_rect(layer, x, y, x, y, grow, net)

    def free(self, layer, cx, cy, net, radius):
        """True when a track or via of this net with the given extra radius fits at the cell."""
        g = self.g
        r = int(math.ceil(radius / GRID))
        x1, x2, y1, y2 = cx - r, cx + r + 1, cy - r, cy + r + 1
        if x1 < 0 or y1 < 0 or x2 > g.w or y2 > g.h:
            return False
        view = g.owner[layer, y1:y2, x1:x2]
        yy, xx = np.ogrid[-r:r + 1, -r:r + 1]
        inside = (xx * xx + yy * yy) * GRID * GRID <= radius * radius + 1e-9
        return bool(np.all((view[inside] == FREE) | (view[inside] == net)))

    def search(self, name, sources, targets):
        """A* over (layer, x, y). Sources and targets are sets of nodes."""
        net = self.nid(name)
        g = self.g
        # One extra grid step because the disc check only samples grid cells
        extra = max(WIDTH.get(name, TRACK) - TRACK, 0) / 2 + GRID if name in WIDTH else 0
        via_r = VIA_D / 2 - TRACK / 2 + GRID
        tx1, tx2 = min(t[1] for t in targets), max(t[1] for t in targets)
        ty1, ty2 = min(t[2] for t in targets), max(t[2] for t in targets)
        cells = g.owner.tolist()  # plain lists are far faster than numpy for one-at-a-time reads

        def h(cx, cy):
            dx = max(tx1 - cx, 0, cx - tx2)
            dy = max(ty1 - cy, 0, cy - ty2)
            return max(dx, dy) + 0.414 * min(dx, dy)

        best = {}
        came = {}
        heap = []
        for s in sources:
            best[s] = 0.0
            heapq.heappush(heap, (h(s[1], s[2]), 0.0, s))
        count = 0
        while heap:
            _, cost, node = heapq.heappop(heap)
            if cost > best.get(node, 1e18):
                continue
            if node in targets:
                path = [node]
                while path[-1] in came:
                    path.append(came[path[-1]])
                return path[::-1]
            count += 1
            if count > 400000:
                return None
            layer, cx, cy = node
            owner = cells[layer]
            for dx, dy, step in MOVES:
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < g.w and 0 <= ny < g.h):
                    continue
                o = owner[ny][nx]
                if o != FREE and o != net:
                    continue
                if extra and not self.free(layer, nx, ny, net, extra):
                    continue
                nc = cost + step
                nn = (layer, nx, ny)
                if nc < best.get(nn, 1e18):
                    best[nn] = nc
                    came[nn] = node
                    heapq.heappush(heap, (nc + h(nx, ny) * 1.15, nc, nn))
            other = (1 - layer, cx, cy)
            nc = cost + VIA_COST
            if nc < best.get(other, 1e18) and (cx, cy) not in self.no_via \
                    and self.free(0, cx, cy, net, via_r) and self.free(1, cx, cy, net, via_r):
                best[other] = nc
                came[other] = node
                heapq.heappush(heap, (nc + h(cx, cy) * 1.15, nc, other))
        return None

    def pad_nodes(self, pad, name):
        """Grid cells inside the pad that a track of this net may use."""
        g = self.g
        nodes = set()
        net = self.nid(name)
        c1 = g.cell(pad["x1"], pad["y1"])
        c2 = g.cell(pad["x2"], pad["y2"])
        for cy in range(c1[1], c2[1] + 1):
            for cx in range(c1[0], c2[0] + 1):
                x, y = g.pos(cx, cy)
                if not (pad["x1"] + 0.02 <= x <= pad["x2"] - 0.02 and pad["y1"] + 0.02 <= y <= pad["y2"] - 0.02):
                    continue
                if pad["round"] and (x - pad["x"]) ** 2 + (y - pad["y"]) ** 2 > ((pad["x2"] - pad["x1"]) / 2 - 0.02) ** 2:
                    continue
                for layer in pad["layers"]:
                    if 0 <= cy < g.h and 0 <= cx < g.w and g.owner[layer, cy, cx] in (net, FREE):
                        nodes.add((layer, cx, cy))
        return nodes

    def path_items(self, path, name, pad_a, pad_b):
        g = self.g
        items = []
        i = 0
        while i < len(path) - 1:
            layer = path[i][0]
            if path[i + 1][0] != layer:
                x, y = g.pos(path[i][1], path[i][2])
                items.append(("via", x, y))
                i += 1
                continue
            j = i + 1
            dx, dy = path[j][1] - path[i][1], path[j][2] - path[i][2]
            while j + 1 < len(path) and path[j + 1][0] == layer and \
                    (path[j + 1][1] - path[j][1], path[j + 1][2] - path[j][2]) == (dx, dy):
                j += 1
            x1, y1 = g.pos(path[i][1], path[i][2])
            x2, y2 = g.pos(path[j][1], path[j][2])
            items.append(("track", layer, x1, y1, x2, y2))
            i = j
        return items

    def centre_stub(self, pad, node):
        """Joins the pad centre to where the path enters the pad, on the same layer."""
        x, y = self.g.pos(node[1], node[2])
        if abs(x - pad["x"]) < 1e-6 and abs(y - pad["y"]) < 1e-6:
            return []
        return [("track", node[0], pad["x"], pad["y"], x, y)]

    def route_net(self, name):
        pads = [p for p in self.pads if p["net"] == name and not p["npth"]]
        seen, unique = set(), []
        for p in pads:
            key = (round(p["x"], 3), round(p["y"], 3))
            if key not in seen:
                seen.add(key)
                unique.append(p)
        pads = unique
        all_pads = list(unique)
        if name in self.fan_via:
            # U1's pins already have stubs and vias, so join those vias to the other pads
            items = self.routes[name]
            vias = [{(0, cx, cy), (1, cx, cy)} for cx, cy in self.fan_via[name]]
            tree = set(vias[0])
            goals = [(via, None) for via in vias[1:]]
            pads = [p for p in pads if p["ref"] != "U1"]
        else:
            items = []
            self.routes[name] = items
            first = min(pads, key=lambda p: (p["x"], p["y"]))
            tree = self.pad_nodes(first, name)
            pads = [p for p in pads if p is not first]
            goals = []
            self.first_pad = first
        goals += [(None, p) for p in pads]
        while goals:
            mid_x = sum(n[1] for n in tree) / len(tree) * GRID + self.g.x0
            mid_y = sum(n[2] for n in tree) / len(tree) * GRID + self.g.y0

            def distance(goal):
                via, pad = goal
                if pad is not None:
                    return abs(pad["x"] - mid_x) + abs(pad["y"] - mid_y)
                _, cx, cy = next(iter(via))
                x, y = self.g.pos(cx, cy)
                return abs(x - mid_x) + abs(y - mid_y)

            goals.sort(key=distance)
            via, pad = goals.pop(0)
            targets = via if via is not None else self.pad_nodes(pad, name)
            if not targets or not tree:
                return False
            path = self.search(name, tree, targets)
            if path is None:
                return False
            new_items = self.path_items(path, name, None, pad)
            if pad is not None:
                new_items += self.centre_stub(pad, path[-1])
            # The search may leave from any pad already joined, not just the first.
            start_pad = next((p for p in all_pads if path[0] in self.pad_nodes(p, name)), None)
            if start_pad is not None:
                new_items += self.centre_stub(start_pad, path[0])
            items.extend(new_items)
            for item in new_items:
                self.paint_item(item, self.nid(name), WIDTH.get(name, TRACK))
            tree |= set(path) | set(targets)
        return True

    def plane_fanout(self, name):
        """Short stub from each surface pad on a plane net (or FAN_IN net) to a via."""
        items = []
        self.routes[name] = items
        net = self.nid(name)
        via_r = VIA_D / 2 - TRACK / 2 + GRID
        ok = True
        for pad in self.pads:
            if pad["net"] != name or pad["npth"] or pad["round"] or (name in FAN_IN and pad["ref"] != "U1"):
                continue
            nodes = self.pad_nodes(pad, name)
            if not nodes:
                ok = False
                continue
            start = min(nodes, key=lambda n: (n[1] - (pad["x"] - self.g.x0) / GRID) ** 2 + (n[2] - (pad["y"] - self.g.y0) / GRID) ** 2)
            # Prefer a via under the chip; a pin hemmed in by its neighbours may use one outside.
            # A via in a pad is the last resort, as it can draw solder away from the joint.
            goal = None
            for inside_only, clear_of_pads in ((True, True), (False, True), (False, False)):
                seen = {start: None}
                queue = [(0.0, start)]
                goal = self.find_via(pad, name, net, via_r, start, seen, queue, inside_only, clear_of_pads)
                if goal is not None:
                    if not clear_of_pads:
                        print("via in pad:", pad["ref"], pad["num"], name)
                    break
            if goal is None:
                print("no via spot:", pad["ref"], pad["num"], name)
                ok = False
                continue
            path = [goal]
            while seen[path[-1]] is not None:
                path.append(seen[path[-1]])
            path.reverse()
            new_items = self.path_items(path, name, None, None) if len(path) > 1 else []
            new_items += self.centre_stub(pad, start)
            x, y = self.g.pos(goal[1], goal[2])
            new_items.append(("via", x, y))
            items.extend(new_items)
            self.fan_via.setdefault(name, []).append((goal[1], goal[2]))
            for item in new_items:
                self.paint_item(item, net, TRACK)
        return ok

    def find_via(self, pad, name, net, via_r, start, seen, queue, inside_only, clear_of_pads):
        """Nearest cell, reachable on the pad's layer, with room for a via."""
        while queue:
            d, node = heapq.heappop(queue)
            layer, cx, cy = node
            x, y = self.g.pos(cx, cy)
            wanted = not inside_only or pad["ref"] != "U1" or (abs(x - self.u1[0]) < BODY and abs(y - self.u1[1]) < BODY)
            if clear_of_pads and (cx, cy) in self.no_via:
                wanted = False
            if wanted and self.free(0, cx, cy, net, via_r) and self.free(1, cx, cy, net, via_r):
                return node
            if d > 6 / GRID:
                return None
            for dx, dy, step in MOVES:
                nn = (layer, cx + dx, cy + dy)
                if nn in seen or not (0 <= nn[1] < self.g.w and 0 <= nn[2] < self.g.h):
                    continue
                if self.g.owner[layer, nn[2], nn[1]] not in (net, FREE):
                    continue
                seen[nn] = node
                heapq.heappush(queue, (d + step, nn))
        return None


def route_usb(router):
    """Hand layout: both lines run straight on F.Cu from J1 to U1 pins 7 and 8, so their main
    lengths match. The ESD diode pads branch off between them. Short B.Cu bridges join the
    connector's second row, which only one plug orientation uses."""
    def pad(ref, num):
        return next(p for p in router.pads if p["ref"] == ref and p["num"] == num)

    dn, dp = pad("U1", "7"), pad("U1", "8")
    b7, a6, a7, b6 = pad("J1", "B7"), pad("J1", "A6"), pad("J1", "A7"), pad("J1", "B6")
    d2, d3 = pad("D1", "2"), pad("D1", "3")
    y_dn, y_dp = dn["y"], dp["y"]
    assert abs(b7["y"] - y_dn) < 0.01 and abs(a6["y"] - y_dp) < 0.01, "J1 and U1 are not aligned"
    assert d2["y"] < y_dn and d3["y"] > y_dp, "D1 is the wrong way round"
    x_dn, x_dp = b7["x"] + 1.3, b7["x"] + 2.05  # bridge via columns, clear of the J1 pads
    neck_end[0] = x_dp + 0.4
    router.routes["/USB_DN"] = [
        ("track", 0, b7["x"], y_dn, neck_end[0], y_dn),
        ("track", 0, neck_end[0], y_dn, dn["x"], y_dn),
        ("track", 0, d2["x"], d2["y"], d2["x"], y_dn),
        ("track", 0, a7["x"], a7["y"], x_dn, a7["y"]),
        ("via", x_dn, a7["y"]),
        ("track", 1, x_dn, a7["y"], x_dn, y_dn - 0.45),
        ("via", x_dn, y_dn - 0.45),
        ("track", 0, x_dn, y_dn - 0.45, x_dn, y_dn),
    ]
    router.routes["/USB_DP"] = [
        ("track", 0, a6["x"], y_dp, neck_end[0], y_dp),
        ("track", 0, neck_end[0], y_dp, dp["x"], y_dp),
        ("track", 0, d3["x"], d3["y"], d3["x"], y_dp),
        ("track", 0, b6["x"], b6["y"], x_dp, b6["y"]),
        ("via", x_dp, b6["y"]),
        ("track", 1, x_dp, b6["y"], x_dp, y_dp + 0.45),
        ("via", x_dp, y_dp + 0.45),
        ("track", 0, x_dp, y_dp + 0.45, x_dp, y_dp),
    ]
    for name in FIRST:
        for item in router.routes[name]:
            router.paint_item(item, router.nid(name), WIDTH[name])


def write(board, routes):
    for track in list(board.GetTracks()):
        board.Remove(track)
    for zone in list(board.Zones()):
        board.Remove(zone)
    placed_vias = set()
    for name, items in routes.items():
        info = board.FindNet(name)
        width = pcbnew.FromMM(WIDTH.get(name, TRACK))
        for item in items:
            if item[0] == "via":
                # Two routes of one net can end on the same via. Drilling it twice can break the drill.
                if item[1:3] in placed_vias:
                    continue
                placed_vias.add(item[1:3])
                via = pcbnew.PCB_VIA(board)
                via.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(item[1]), pcbnew.FromMM(item[2])))
                via.SetViaType(pcbnew.VIATYPE_THROUGH)
                via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                via.SetWidth(pcbnew.FromMM(VIA_D))
                via.SetDrill(pcbnew.FromMM(VIA_DRILL))
                via.SetNet(info)
                board.Add(via)
            else:
                _, layer, x1, y1, x2, y2 = item
                if abs(x1 - x2) < 1e-6 and abs(y1 - y2) < 1e-6:
                    continue
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
                t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x2), pcbnew.FromMM(y2)))
                t.SetLayer(LAYERS[layer])
                t.SetWidth(pcbnew.FromMM(USB_NECK) if name in FIRST and max(x1, x2) <= neck_end[0] else width)
                t.SetNet(info)
                board.Add(t)


def add_zones(board):
    box = board.GetBoardEdgesBoundingBox()
    fills = [("/GND", pcbnew.In1_Cu), ("/+3V3", pcbnew.In2_Cu), ("/GND", pcbnew.F_Cu), ("/GND", pcbnew.B_Cu)]
    for name, layer in fills:
        zone = pcbnew.ZONE(board)
        zone.SetLayer(layer)
        zone.SetNet(board.FindNet(name))
        zone.SetMinThickness(pcbnew.FromMM(0.2))
        zone.SetLocalClearance(pcbnew.FromMM(0.2))
        zone.SetThermalReliefGap(pcbnew.FromMM(0.25))
        zone.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.3))
        outline = zone.Outline()
        outline.NewOutline()
        for x, y in [(box.GetLeft(), box.GetTop()), (box.GetRight(), box.GetTop()),
                     (box.GetRight(), box.GetBottom()), (box.GetLeft(), box.GetBottom())]:
            outline.Append(x, y)
        board.Add(zone)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())


def set_rules(path):
    """Writes the rules into the project file, which is where kicad-cli reads them from.
    Limits are close to what 4-layer fabs offer: VERIFY on the fab's capability page before ordering."""
    pro = path.replace(".kicad_pcb", ".kicad_pro")
    with open(pro, encoding="utf8") as f:
        data = json.load(f)
    rules = data["board"]["design_settings"]["rules"]
    rules.update(min_clearance=0.127, min_track_width=0.127, min_via_annular_width=0.15, min_via_diameter=0.45,
                 min_through_hole_diameter=0.2, min_hole_clearance=0.2, min_hole_to_hole=0.25,
                 min_copper_edge_clearance=0.3, min_text_height=0.6, min_resolved_spokes=1)
    for netclass in data["net_settings"]["classes"]:
        if netclass["name"] == "Default":
            netclass.update(clearance=0.127, track_width=TRACK, via_diameter=VIA_D, via_drill=VIA_DRILL)
    with open(pro, "w", encoding="utf8") as f:
        json.dump(data, f, indent=2)


def drop_idle_vias(routes):
    """Removes vias on signal nets with tracks on only one side, left behind by the maze search."""
    cleaned = {}
    for name, items in routes.items():
        if name in PLANES:
            cleaned[name] = items
            continue
        kept = []
        for item in items:
            if item[0] == "via":
                touching = set()
                for other in items:
                    if other[0] == "track":
                        for x, y in ((other[2], other[3]), (other[4], other[5])):
                            if abs(x - item[1]) < 1e-6 and abs(y - item[2]) < 1e-6:
                                touching.add(other[1])
                if len(touching) < 2:
                    continue
            kept.append(item)
        cleaned[name] = kept
    return cleaned


def save(path, routes):
    """A fresh load avoids pcbnew failing to remove zones this same process added."""
    fresh = pcbnew.LoadBoard(path)
    write(fresh, drop_idle_vias(routes))
    add_zones(fresh)
    pcbnew.SaveBoard(path, fresh)
    set_rules(path)  # SaveBoard rewrites the project file with its own defaults


def repair(router, failed, signal, seed):
    """Rips up a few routed nets around each failure and tries again. Keeps only improvements."""
    rng = random.Random(seed)
    for step in range(600):
        if not failed:
            break
        before = {name: list(items) for name, items in router.routes.items()}
        target = rng.choice(failed)
        others = [n for n in signal if n not in failed]
        ripped = rng.sample(others, min(rng.randint(1, 5), len(others)))
        for name in failed + ripped:
            router.routes[name] = list(router.fan_items.get(name, []))
        router.rebuild()
        router.close_body()
        now = []
        for name in [target] + [n for n in failed if n != target] + ripped:
            if not router.route_net(name):
                now.append(name)
        if len(now) <= len(failed):
            if len(now) < len(failed):
                print(f"repair step {step}: failed {now}", flush=True)
            failed = now
        else:
            router.routes = before
    router.rebuild()
    return failed


def main():
    path = sys.argv[1]
    board = pcbnew.LoadBoard(path)
    router = Router(board)
    signal = sorted({p["net"] for p in router.pads if p["net"] and not p["net"].startswith("unconnected")
                     and p["net"] not in PLANES and sum(q["net"] == p["net"] for q in router.pads) > 1})
    failed = []
    router.routes = {}
    router.fan_via = {}
    router.rebuild()
    # USB first, then every via under U1, then power, then everything else
    route_usb(router)
    for name in list(PLANES) + FAN_IN:
        if not router.plane_fanout(name):
            failed.append(name)
    router.fan_items = {name: list(router.routes[name]) for name in FAN_IN if name in router.routes}
    router.close_body()
    router.close_back_under_u1(True)
    for name in POWER:
        if not router.route_net(name):
            failed.append(name)
    router.close_back_under_u1(False)
    rest = [n for n in signal if n not in FIRST and n not in EARLY and n not in POWER]
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    random.Random(seed).shuffle(rest)
    for name in EARLY + rest:
        if name in signal and not router.route_net(name):
            failed.append(name)
    print("first pass failed", failed, flush=True)
    save(path, router.routes)
    failed = repair(router, failed, [n for n in signal if n not in FIRST and n not in POWER], seed)
    save(path, router.routes)
    print("failed", failed)


if __name__ == "__main__":
    main()
