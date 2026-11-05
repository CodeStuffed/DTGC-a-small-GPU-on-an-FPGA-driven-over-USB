#!/usr/bin/env python3
"""Usage: python scripts/run_tests.py [--quick] [--seeds N]

Runs every simulation and software test, prints PASS or FAIL for each, and exits non-zero if any
fail. Needs Icarus Verilog on the PATH (OSS CAD Suite). A pass means "passes simulation": it says
nothing about real hardware.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

BUILD = Path("build/sim")


def simulate(name, sources, plusargs=(), compile_args=()):
    """Compiles and runs one testbench. Passes only if it prints PASS and never prints FAIL."""
    out = BUILD / f"{name}.vvp"
    compiled = subprocess.run(["iverilog", "-g2005", *compile_args, "-o", str(out), *sources],
                              capture_output=True, text=True)
    if compiled.returncode != 0:
        return False, compiled.stderr.strip()
    run = subprocess.run(["vvp", str(out), *plusargs], capture_output=True, text=True)
    lines = run.stdout.splitlines()
    ok = run.returncode == 0 and any(l.startswith("PASS") for l in lines) \
        and not any(l.startswith("FAIL") for l in lines)
    summary = next((l for l in reversed(lines) if l.startswith(("PASS", "FAIL"))), "no result printed")
    return ok, summary


def main():
    parser = argparse.ArgumentParser(description="Run all simulations.")
    parser.add_argument("--quick", action="store_true", help="fewer seeds and frames")
    parser.add_argument("--seeds", type=int, default=None, help="random seeds for each randomised test")
    args = parser.parse_args()
    seeds = args.seeds or (3 if args.quick else 30)
    frames = 3 if args.quick else 8
    BUILD.mkdir(parents=True, exist_ok=True)

    tests = [
        ("blink_tb", ["sim/blink_tb.v", "rtl/blink.v"], ()),
        ("video_timing_tb", ["sim/video_timing_tb.v", "rtl/video_timing.v"], ()),
        ("video_timing_hd_tb", ["sim/video_timing_hd_tb.v", "rtl/video_timing.v"], ()),
        ("tmds_encoder_tb", ["sim/tmds_encoder_tb.v", "rtl/tmds_encoder.v"], ()),
        ("upscale_edge_tb", ["sim/upscale_edge_tb.v", "rtl/upscale_edge.v"], ()),
        ("upscale_filter_tb_x2", ["sim/upscale_filter_tb.v", "rtl/upscale_filter.v"], (), ("-Pupscale_filter_tb.SCALE=2",)),
        ("upscale_filter_tb_x3", ["sim/upscale_filter_tb.v", "rtl/upscale_filter.v"], (), ("-Pupscale_filter_tb.SCALE=3",)),
    ]
    # UART: the same rate both ways at 3 Mbaud, 1 Mbaud and 115200, then the receiver 2% fast and slow.
    for tx_inc, rx_inc in ((7802, 7802), (2601, 2601), (300, 300), (7802, 7958), (7802, 7646)):
        tests.append((f"uart_tb_{tx_inc}_{rx_inc}", ["sim/uart_tb.v", "rtl/uart_tx.v", "rtl/uart_rx.v"],
                      (), (f"-Puart_tb.TX_INC={tx_inc}", f"-Puart_tb.RX_INC={rx_inc}")))
    sdram = ["sim/sdram_ctrl_tb.v", "sim/sdram_model.v", "rtl/sdram_ctrl.v"]
    for seed in range(1, seeds + 1):
        tests.append((f"sdram_ctrl_tb_{seed}", sdram, (f"+seed={seed}", "+ops=40000")))
    tests.append(("fb_core_tb",
                  ["sim/fb_core_tb.v", "sim/sdram_model.v", "rtl/fb_core.v", "rtl/video_timing.v",
                   "rtl/sdram_ctrl.v", "rtl/fb_scanout.v", "rtl/fb_pattern.v"],
                  (f"+frames={frames}", f"+ppm={BUILD / 'fb_core_tb.ppm'}")))
    # The FT2232H link, against our model of the chip: stalls from both sides, and its clock stopping.
    ft_link = ["sim/ft_link_tb.v", "sim/ft2232h_model.v", "rtl/ft_link.v", "rtl/ft_bus.v", "rtl/async_fifo.v"]
    for stalls in ((0, 0, 0, 0), (30, 0, 0, 0), (0, 30, 0, 0), (0, 0, 70, 0), (50, 50, 50, 0), (90, 90, 0, 0),
                   (0, 0, 95, 0), (20, 20, 20, 5)):
        rx, tx, gpu, gaps = stalls
        for seed in range(1, min(seeds, 3) + 1):
            tests.append((f"ft_link_tb_{rx}_{tx}_{gpu}_{gaps}_{seed}", ft_link,
                          (f"+seed={seed}", "+bytes=4000", f"+rxstall={rx}", f"+txstall={tx}", f"+gpustall={gpu}",
                           f"+clockgaps={gaps}")))

    failures = 0
    for name, *test in tests:
        ok, summary = simulate(name, *test)
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {summary}", flush=True)

    # Python tests, if there are any yet.
    if list(Path("sw/tests").glob("test_*.py")):
        run = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "sw/tests", "-t", "."],
                             capture_output=True, text=True, env={**os.environ, "DTGC_RTL_SEEDS": str(4 if args.quick else 20)})
        failures += run.returncode != 0
        print(f"{'PASS' if run.returncode == 0 else 'FAIL'}  python tests: "
              f"{run.stderr.strip().splitlines()[-1]}")
        if run.returncode != 0:
            print(run.stderr)

        # The 960x540 picture for 1080p30. A separate run, because the size is read once when the protocol is imported.
        run = subprocess.run([sys.executable, "-m", "unittest", "sw.tests.test_rtl_match.LargePictureMatchesEmulator",
                              "sw.tests.test_upscale_rtl.HdScanoutMatchesTheModel.test_1080p30_filling_the_screen"],
                             capture_output=True, text=True, env={**os.environ, "DTGC_PICTURE": "960x540", "DTGC_RTL_SEEDS": "2"})
        failures += run.returncode != 0
        print(f"{'PASS' if run.returncode == 0 else 'FAIL'}  960x540 picture and 1080p30 screen: "
              f"{run.stderr.strip().splitlines()[-1]}")
        if run.returncode != 0:
            print(run.stderr)

    print(f"\n{len(tests)} simulations run, {failures} failed. Simulation only, not hardware.")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
