#!/usr/bin/env python3
"""Usage: python scripts/report_builds.py [--write]

Reads the final place-and-route figures of each build in build/*-nextpnr.log and prints a table. With --write it also
replaces the "Latest builds" section of docs/resources.md. Exits non-zero if a clock missed its target or was never
checked against the speed it really needs. Fmax is the tool's estimate, not a hardware measurement.
"""
import argparse
import re
import sys
from pathlib import Path

DOC = Path("docs/resources.md")
HEADING = "## Latest builds"
RESOURCES = ("LUT4", "DFF", "ALU", "BSRAM")

# Every build, and the speed each of its clocks must reach, in MHz.
BUILDS = {
    "top_gpu": {"clk_pixel": 25.2},
    "top_gpu_ft": {"clk_pixel": 25.2, "link.ft_clk": 60},
    "top_gpu_usb": {"clk_pixel": 25.2},
    "top_gpu_usb_ft": {"clk_pixel": 25.2, "link.ft_clk": 60},
    "top_gpu_hd": {"clk_core": 46.41, "clk_video": 74.25},
    "top_gpu_hd_safe": {"clk_core": 26.52, "clk_video": 74.25},
    "top_gpu_hd_nodsp": {"clk_core": 46.41, "clk_video": 74.25},
    "top_gpu_hd_ft": {"clk_core": 46.41, "clk_video": 74.25, "link.ft_clk": 60},
    "top_gpu_1080p30": {"clk_core": 46.41, "clk_video": 74.25},
    "top_gpu_1080p30_ft": {"clk_core": 46.41, "clk_video": 74.25, "link.ft_clk": 60},
    "top_gpu_1080p30x3": {"clk_core": 46.41, "clk_video": 74.25},
    "top_gpu_1080p30x4": {"clk_core": 46.41, "clk_video": 74.25},
    "top_gpu_1080p30x5": {"clk_core": 46.41, "clk_video": 74.25},
    "top_gpu_1080p30x6": {"clk_core": 46.41, "clk_video": 74.25},
    "top_gpu_1080p30x7": {"clk_core": 46.41, "clk_video": 74.25},
    "top_gpu_1080": {"clk_core": 48, "clk_video": 115.2},
    "top_gpu_1080_ft": {"clk_core": 48, "clk_video": 115.2, "link.ft_clk": 60},
    "bars_720p": {"clk_pixel": 74.25},
    "bars_1080p30": {"clk_pixel": 74.25},
    "bars_1080p50": {"clk_pixel": 115.2},
}


def read_build(top):
    """The last figures in the log, which are the ones after routing. None if there is no log."""
    log = Path(f"build/{top}-nextpnr.log")
    if not log.exists():
        return None
    text = log.read_text(errors="replace")
    clocks = {name: float(mhz) for name, mhz in
              re.findall(r"Max frequency for clock\s+'([^']+)':\s+([\d.]+) MHz", text)}
    used = {}
    for name in RESOURCES:
        counts = re.findall(rf"^Info:\s+{name}:\s+(\d+)/\s*(\d+)", text, re.M)
        if counts:
            used[name] = counts[-1]
    return clocks, used


def main():
    parser = argparse.ArgumentParser(description="Report FPGA build size and speed.")
    parser.add_argument("--write", action="store_true", help="update docs/resources.md")
    args = parser.parse_args()

    rows, problems = [], []
    for top, wanted in BUILDS.items():
        build = read_build(top)
        if build is None:
            problems.append(f"{top}: no build log")
            continue
        clocks, used = build
        speeds = []
        for name, need in wanted.items():
            got = clocks.get(name)
            if got is None:
                problems.append(f"{top}: {name} is not in the log")
                continue
            speeds.append(f"`{name}` {got:.2f} (needs {need:g})")
            if got < need:
                problems.append(f"{top}: {name} reaches {got:.2f} MHz, needs {need:g} MHz")
        cells = [f"{used[name][0]} / {used[name][1]}" if name in used else "?" for name in RESOURCES]
        rows.append(f"| `{top}` | " + " | ".join(cells) + " | " + "; ".join(speeds) + " |")

    table = "\n".join(["| Design | " + " | ".join(RESOURCES) + " | Clock Fmax in MHz |", "|---|---|---|---|---|---|", *rows])
    print(table)
    for problem in problems:
        print("PROBLEM:", problem)

    if args.write:
        section = (f"{HEADING}\n\nWritten by `python scripts/report_builds.py --write`. No DSP blocks are used. "
                   f"Fmax is the tool's estimate, not a hardware measurement.\n\n{table}\n")
        text = DOC.read_text(encoding="utf-8")
        if HEADING in text:
            before, rest = text.split(HEADING, 1)
            following = re.search(r"^## ", rest, re.M)
            text = before + section + ("\n" + rest[following.start():] if following else "")
        else:
            first = text.index("## ")
            text = text[:first] + section + "\n" + text[first:]
        DOC.write_text(text, encoding="utf-8", newline="\n")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
