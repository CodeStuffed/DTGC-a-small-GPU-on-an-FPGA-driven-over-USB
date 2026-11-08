#!/usr/bin/env python3
"""Usage: python scripts/build_all.py [NAME...]

Builds the bitstreams in build/ from the current Verilog, in the order the hardware tests use them.
With no names it builds all of them. Names: blink, colorbars, framebuffer, gpu, gpu_ft, gpu_usb, gpu_usb_ft, gpu_hd, gpu_hd_ft, gpu_1080, gpu_1080_ft, gpu_1080p30, gpu_1080p30_ft,
gpu_1080p30x3 to gpu_1080p30x7 (and _ft),
bars_720p, bars_1080p30, bars_1080p50.
"""
import subprocess
import sys
from pathlib import Path

HD = ["rtl/fb_scanout_hd.v", "rtl/upscale_filter.v", "rtl/upscale_edge.v"]
VIDEO = ["rtl/video_timing.v", "rtl/tmds_encoder.v", "rtl/hdmi_out.v", "rtl/video_clocks.v"]
GPU = ["rtl/gpu_core.v", "rtl/cmd_exec.v", "rtl/raster.v", "rtl/vertex_store.v", "rtl/depth_flags.v", "rtl/frame_reader.v", "rtl/pkt_parser.v", "rtl/reply_tx.v", "rtl/byte_fifo.v",
       "rtl/sdram_ctrl.v", "rtl/fb_scanout.v", *VIDEO]

# 1920x1080 at 50 Hz with reduced blanking: 27 x 64 / 3 = 576 MHz serial, 115.2 MHz video, 26.18 MHz core.
MODE_1080 = [item for pair in (("IDIV_SEL", 2), ("FBDIV_SEL", 63), ("ODIV_SEL", 2), ("SDIV_SEL", 12), ("SCALE", 3),
                               ("H_VISIBLE", 1920), ("H_FRONT", 48), ("H_SYNC", 32), ("H_BACK", 80),
                               ("V_VISIBLE", 1080), ("V_FRONT", 3), ("V_SYNC", 5), ("V_BACK", 20))
             for item in ("--param", f"{pair[0]}={pair[1]}")]

# 1920x1080 at 30 Hz, standard timing, filled by a 960x540 picture twice the size. The same 371.25 MHz serial clock as 720p60.
MODE_1080P30 = [item for pair in (("SCALE", 2), ("EDGE", 1), ("WIDTH", 960), ("HEIGHT", 540), ("LINE_WORDS", 240),
                                  ("H_VISIBLE", 1920), ("H_FRONT", 88), ("H_SYNC", 44), ("H_BACK", 148),
                                  ("V_VISIBLE", 1080), ("V_FRONT", 4), ("V_SYNC", 5), ("V_BACK", 36))
                for item in ("--param", f"{pair[0]}={pair[1]}")]

# "Super upscale": the same 1080p30 screen filled by a smaller picture scaled 3 to 7 times, edge-directed. Fewer pixels
# to draw leaves more of each frame's time spare, for a softer picture. 1080 / 7 is not whole, so x7 has a 1 pixel border.
SUPER = {3: (640, 360), 4: (480, 270), 5: (384, 216), 6: (320, 180), 7: (274, 154)}


def mode_super(scale):
    width, height = SUPER[scale]
    pairs = (("SCALE", scale), ("EDGE", 1), ("WIDTH", width), ("HEIGHT", height), ("LINE_WORDS", (width + 3) // 4),
             ("H_VISIBLE", 1920), ("H_FRONT", 88), ("H_SYNC", 44), ("H_BACK", 148),
             ("V_VISIBLE", 1080), ("V_FRONT", 4), ("V_SYNC", 5), ("V_BACK", 36))
    return [item for pair in pairs for item in ("--param", f"{pair[0]}={pair[1]}")]

# The colour-bar ladder for a real monitor (docs/first-hardware.md, section G). There is no 1080p60 entry on purpose: its
# PLL settings go over the chip's listed limits (docs/hd-limits.md).
def bars(name, freq, *pairs):
    params = [item for pair in pairs for item in ("--param", f"{pair[0]}={pair[1]}")]
    return ("top_bars_hd", "constraints/hdmi.cst", ["rtl/top_bars_hd.v", *VIDEO], ["--name", name, "--freq", freq, *params])


DESIGNS = {
    "bars_720p": bars("bars_720p", "74.25", ("H_VISIBLE", 1280), ("H_FRONT", 110), ("H_SYNC", 40), ("H_BACK", 220),
                      ("V_VISIBLE", 720), ("V_FRONT", 5), ("V_SYNC", 5), ("V_BACK", 20)),
    "bars_1080p30": bars("bars_1080p30", "74.25"),
    "bars_1080p50": bars("bars_1080p50", "115.2", ("IDIV_SEL", 2), ("FBDIV_SEL", 63), ("H_VISIBLE", 1920), ("H_FRONT", 48),
                         ("H_SYNC", 32), ("H_BACK", 80), ("V_VISIBLE", 1080), ("V_FRONT", 3), ("V_SYNC", 5), ("V_BACK", 20)),
    "blink": ("blink", "constraints/blink.cst", ["rtl/blink.v"], ["--freq", "27"]),
    "colorbars": ("top_colorbars", "constraints/hdmi.cst", ["rtl/top_colorbars.v", *VIDEO], ["--freq", "25.2"]),
    "framebuffer": ("top_framebuffer", "constraints/framebuffer.cst",
                    ["rtl/top_framebuffer.v", "rtl/fb_core.v", "rtl/fb_pattern.v", "rtl/sdram_ctrl.v", "rtl/fb_scanout.v", *VIDEO],
                    ["--freq", "25.2"]),
    "gpu": ("top_gpu", "constraints/gpu.cst", ["rtl/top_gpu.v", "rtl/uart_rx.v", "rtl/uart_tx.v", *GPU], ["--freq", "25.2"]),
    "gpu_ft": ("top_gpu_ft", "constraints/gpu_ft.cst",
               ["rtl/top_gpu_ft.v", "rtl/ft_link.v", "rtl/ft_bus.v", "rtl/async_fifo.v", *GPU],
               ["--freq", "25.2", "--sdc", "constraints/gpu_ft.sdc", "--pack-flag", "sspi_as_gpio", "--pack-flag", "cpu_as_gpio"]),
    "gpu_hd": ("top_gpu_hd", "constraints/gpu.cst", ["rtl/top_gpu_hd.v", "rtl/uart_rx.v", "rtl/uart_tx.v", *HD, *GPU],
               ["--freq", "74.25", "--sdc", "constraints/gpu_hd.sdc"]),
    # The same design with the core and SDRAM at the slower clock, in case the memory pins do not keep up on real hardware.
    "gpu_hd_safe": ("top_gpu_hd", "constraints/gpu.cst", ["rtl/top_gpu_hd.v", "rtl/uart_rx.v", "rtl/uart_tx.v", *HD, *GPU],
                    ["--name", "top_gpu_hd_safe", "--freq", "74.25", "--sdc", "constraints/gpu_hd.sdc", "--param", "SDIV_SEL=14", "--param", "PHASE_INC=7414"]),
    # And with no hard multipliers, in case the open tools' multiplier bitstream does not behave on the real chip.
    "gpu_hd_nodsp": ("top_gpu_hd", "constraints/gpu.cst", ["rtl/top_gpu_hd.v", "rtl/uart_rx.v", "rtl/uart_tx.v", *HD, *GPU],
                     ["--name", "top_gpu_hd_nodsp", "--freq", "74.25", "--sdc", "constraints/gpu_hd.sdc", "--define", "RASTER_SERIAL_MATH"]),
    "gpu_hd_ft": ("top_gpu_hd_ft", "constraints/gpu_ft.cst",
                  ["rtl/top_gpu_hd_ft.v", "rtl/ft_link.v", "rtl/ft_bus.v", "rtl/async_fifo.v", *HD, *GPU],
                  ["--freq", "74.25", "--sdc", "constraints/gpu_hd_ft.sdc", "--pack-flag", "sspi_as_gpio", "--pack-flag", "cpu_as_gpio"]),
    "gpu_1080p30": ("top_gpu_hd", "constraints/gpu.cst", ["rtl/top_gpu_hd.v", "rtl/uart_rx.v", "rtl/uart_tx.v", *HD, *GPU],
                    ["--name", "top_gpu_1080p30", "--freq", "74.25", "--sdc", "constraints/gpu_hd.sdc", *MODE_1080P30]),
    "gpu_1080p30_ft": ("top_gpu_hd_ft", "constraints/gpu_ft.cst",
                       ["rtl/top_gpu_hd_ft.v", "rtl/ft_link.v", "rtl/ft_bus.v", "rtl/async_fifo.v", *HD, *GPU],
                       ["--name", "top_gpu_1080p30_ft", "--freq", "74.25", "--sdc", "constraints/gpu_hd_ft.sdc",
                        "--pack-flag", "sspi_as_gpio", "--pack-flag", "cpu_as_gpio", *MODE_1080P30]),
    "gpu_1080": ("top_gpu_hd", "constraints/gpu.cst", ["rtl/top_gpu_hd.v", "rtl/uart_rx.v", "rtl/uart_tx.v", *HD, *GPU],
                 ["--name", "top_gpu_1080", "--freq", "115.2", "--sdc", "constraints/gpu_hd.sdc", "--param", "PHASE_INC=4096", *MODE_1080]),
    "gpu_1080_ft": ("top_gpu_hd_ft", "constraints/gpu_ft.cst",
                    ["rtl/top_gpu_hd_ft.v", "rtl/ft_link.v", "rtl/ft_bus.v", "rtl/async_fifo.v", *HD, *GPU],
                    ["--name", "top_gpu_1080_ft", "--freq", "115.2", "--sdc", "constraints/gpu_hd_ft.sdc",
                     "--pack-flag", "sspi_as_gpio", "--pack-flag", "cpu_as_gpio", *MODE_1080]),
    "gpu_usb": ("top_gpu_usb", "constraints/gpu.cst", ["rtl/top_gpu_usb.v", "rtl/uart_rx.v", "rtl/uart_tx.v", *GPU], ["--freq", "25.2"]),
    "gpu_usb_ft": ("top_gpu_usb_ft", "constraints/gpu_ft.cst",
                   ["rtl/top_gpu_usb_ft.v", "rtl/ft_link.v", "rtl/ft_bus.v", "rtl/async_fifo.v", *GPU],
                   ["--freq", "25.2", "--sdc", "constraints/gpu_ft.sdc", "--pack-flag", "sspi_as_gpio", "--pack-flag", "cpu_as_gpio"]),
}
for _n in SUPER:
    DESIGNS[f"gpu_1080p30x{_n}"] = ("top_gpu_hd", "constraints/gpu.cst", ["rtl/top_gpu_hd.v", "rtl/uart_rx.v", "rtl/uart_tx.v", *HD, *GPU],
                                    ["--name", f"top_gpu_1080p30x{_n}", "--freq", "74.25", "--sdc", "constraints/gpu_hd.sdc", *mode_super(_n)])
    DESIGNS[f"gpu_1080p30x{_n}_ft"] = ("top_gpu_hd_ft", "constraints/gpu_ft.cst",
                                       ["rtl/top_gpu_hd_ft.v", "rtl/ft_link.v", "rtl/ft_bus.v", "rtl/async_fifo.v", *HD, *GPU],
                                       ["--name", f"top_gpu_1080p30x{_n}_ft", "--freq", "74.25", "--sdc", "constraints/gpu_hd_ft.sdc",
                                        "--pack-flag", "sspi_as_gpio", "--pack-flag", "cpu_as_gpio", *mode_super(_n)])

SEEDS = ("1", "2", "3", "4", "5")


def main():
    names = sys.argv[1:] or list(DESIGNS)
    unknown = [name for name in names if name not in DESIGNS]
    if unknown:
        sys.exit(f"unknown: {', '.join(unknown)}. Names: {', '.join(DESIGNS)}")
    build = str(Path(__file__).with_name("build.py"))
    seeds = {}
    for name in names:
        top, cst, sources, options = DESIGNS[name]
        print(f"=== {name}", flush=True)
        # The router sometimes gives up on one seed of a design that fits. Each seed still repeats exactly.
        for seed in SEEDS:
            if not subprocess.run([sys.executable, build, top, cst, *sources, *options, "--seed", seed]).returncode:
                seeds[name] = seed
                break
            print(f"=== {name}: seed {seed} failed", flush=True)
        else:
            sys.exit(f"{name} did not build")
    print("All built: " + ", ".join(names))
    print("Seeds other than 1: " + (", ".join(f"{n} {s}" for n, s in seeds.items() if s != "1") or "none"))


if __name__ == "__main__":
    main()
