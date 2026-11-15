#!/usr/bin/env python3
"""Usage: python scripts/make_overview_pic.py BACKPACK_RENDER.png OUT.png

Draws DTGC and xDTGC side by side. The Tang is a plain drawing at its real outline size, not a photo.
The backpack picture is a KiCad 3D render of the real board file. The screen picture is simulation output.
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle
from PIL import Image

TANG_W, TANG_H = 54.04, 22.55
BACKPACK_W, BACKPACK_H = 54.04, 25.0
INK, BLUE, GREEN, GREY = "#1f2933", "#2563a8", "#2f7d4f", "#6b7280"


def box(ax, x, y, w, h, label, face="#eef1f4", size=11):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=1.5", fc=face, ec=INK, lw=1.2))
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center", fontsize=size, color=INK)


def link(ax, start, end, label, color):
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=14, lw=2.4, color=color))
    ax.text((start[0] + end[0]) / 2, start[1] + 2.2, label, ha="center", va="bottom", fontsize=10, color=color)


def tang(ax, x, y):
    ax.add_patch(FancyBboxPatch((x, y), TANG_W, TANG_H, boxstyle="round,pad=0,rounding_size=2.5",
                                fc="#2b2f36", ec=INK, lw=1.2))
    for row in (y + 1.1, y + TANG_H - 1.1):
        for pin in range(20):
            ax.plot(x + 2.87 + pin * 2.54, row, "o", ms=3, color="#d8b24a")
    ax.text(x + TANG_W / 2, y + TANG_H / 2, "Tang Nano 20K\nbought board, nothing to design\n54.04 x 22.55 mm",
            ha="center", va="center", fontsize=11, color="white")


def row(ax, top, title, note, draw_board, usb_label, usb_color):
    ax.text(0, top + 3, title, fontsize=16, fontweight="bold", color=INK)
    ax.text(0, top - 1, note, fontsize=11, color=GREY)
    y = top - 34
    box(ax, 0, y + 4, 24, 18, "PC")
    board_x = 58
    draw_board(ax, board_x, y)
    link(ax, (25, y + 13), (board_x - 1, y + 13), usb_label, usb_color)
    link(ax, (board_x + TANG_W + 1, y + 13), (board_x + TANG_W + 26, y + 13), "HDMI", GREEN)
    monitor_x = board_x + TANG_W + 27
    ax.add_patch(Rectangle((monitor_x, y - 1), 32, 27, fc="#111827", ec=INK))
    ax.imshow(SCREEN, extent=(monitor_x + 1.5, monitor_x + 30.5, y + 0.5, y + 24.5), zorder=2, aspect="auto")
    ax.text(monitor_x + 16, y - 3, "Monitor (picture from simulation)", ha="center", va="top", fontsize=9, color=GREY)


def plain(ax, x, y):
    tang(ax, x, y + 1.5)


def stacked(ax, x, y):
    tang(ax, x + 3, y - 4)
    ax.imshow(BACKPACK, extent=(x, x + BACKPACK_W, y + 2, y + 2 + BACKPACK_H), zorder=3, aspect="auto")
    ax.text(x + BACKPACK_W / 2, y + 2 + BACKPACK_H + 1, "Backpack PCB (3D render of the real KiCad file) plugs on top",
            ha="center", va="bottom", fontsize=9, color=GREY)


render = Image.open(sys.argv[1]).convert("RGB").crop((350, 235, 1218, 637))
BACKPACK = render
SCREEN = Image.open("build/sim/fb_core_tb.png").convert("RGB")

fig, ax = plt.subplots(figsize=(14, 9.2))
row(ax, 92, "DTGC: Tang Nano 20K on its own (Stage 1)",
    "One USB-C cable and one HDMI cable. Speed: assumed about 0.3 MB/s, not yet measured.",
    plain, "USB-C (onboard serial)", BLUE)
row(ax, 42, "xDTGC: Tang Nano 20K + backpack PCB, in a case (Stage 2)",
    "The FT2232H chip gives a faster USB link. Real speed: VERIFY, not built yet.",
    stacked, "USB-C (FT2232H FIFO)", BLUE)
ax.set_xlim(-2, 172)
ax.set_ylim(-5, 100)
ax.axis("off")
fig.text(0.5, 0.012, "Drawings, not photos. Nothing here has been built or tested on hardware. Board positions are not exact.",
         ha="center", fontsize=10, color=GREY)
fig.savefig(sys.argv[2], dpi=130, facecolor="white", bbox_inches="tight")
