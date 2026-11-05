#!/usr/bin/env python3
"""Usage: python scripts/build.py TOP CST_FILE VERILOG_FILE... [--freq MHZ] [--seed N]

Builds a bitstream for the Tang Nano 20K with Yosys, nextpnr-himbaechel and
gowin_pack, writing build/TOP.fs. Stops with an error if timing is not met.
"""
import argparse
import subprocess
import sys
from pathlib import Path

DEVICE = "GW2AR-LV18QN88C8/I7"
FAMILY = "GW2A-18C"


def run(cmd):
    print(">", " ".join(cmd), flush=True)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(f"FAILED ({result.returncode}): {cmd[0]}")


def main():
    parser = argparse.ArgumentParser(description="Build a Tang Nano 20K bitstream.")
    parser.add_argument("top")
    parser.add_argument("cst")
    parser.add_argument("verilog", nargs="+")
    parser.add_argument("--name", help="name for the output files, when one top level is built several ways")
    parser.add_argument("--param", action="append", default=[], metavar="NAME=VALUE", help="set a parameter of the top level")
    parser.add_argument("--define", action="append", default=[], metavar="NAME", help="define a Verilog macro")
    parser.add_argument("--freq", default="27", help="clock target in MHz (default: 27)")
    parser.add_argument("--seed", default="1", help="place and route seed, fixed so builds repeat (default: 1)")
    parser.add_argument("--sdc", help="timing file, for designs with a clock from outside other than --freq")
    parser.add_argument("--pack-flag", action="append", default=[],
                        help="extra gowin_pack flag without the dashes, such as sspi_as_gpio (repeatable)")
    args = parser.parse_args()

    out = Path("build")
    out.mkdir(exist_ok=True)
    name = args.name or args.top
    synth = str(out / f"{name}-synth.json")
    routed = str(out / f"{name}.json")
    bitstream = str(out / f"{name}.fs")
    params = "".join(f"chparam -set {p.split('=')[0]} {p.split('=')[1]} {args.top}; " for p in args.param)

    sources = " ".join(args.verilog)
    run([
        "yosys", "-q", "-l", str(out / f"{name}-yosys.log"), "-p",
        f"read_verilog {''.join(f'-D{name} ' for name in args.define)}{sources}; {params}"
        f"synth_gowin -top {args.top} -json {synth} -family gw2a -setundef",
    ])
    # No --timing-allow-fail: a design that misses timing must not produce a bitstream.
    run([
        "nextpnr-himbaechel", "--seed", args.seed, "--json", synth, "--write", routed,
        "--device", DEVICE, "--vopt", f"family={FAMILY}", "--vopt", f"cst={args.cst}",
        "--freq", args.freq, "--log", str(out / f"{name}-nextpnr.log"),
        *(["--sdc", args.sdc] if args.sdc else []),
    ])
    flags = [f"--{flag}" for flag in args.pack_flag]
    run(["gowin_pack", "-c", *flags, "-d", FAMILY, "-o", bitstream, routed])
    print(f"Built {bitstream}")


if __name__ == "__main__":
    main()
