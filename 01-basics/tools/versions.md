# Installed tools

Installed 2026-10-31 on Windows 11. OSS CAD Suite is in `C:\tools\oss-cad-suite`, release 2026-10-31.

| Tool | Version |
|---|---|
| Yosys | 0.70+286 (63eecf3dd) |
| nextpnr-himbaechel | nextpnr-0.11.1-84-g5e1b0f15 |
| openFPGALoader | v1.2.0 |
| Icarus Verilog (`iverilog`, `vvp`) | 14.0 devel (s20260301-786-g5d0488854-dirty) |
| Verilator (`verilator_bin`) | 5.053 devel |
| Python | 3.14.6 |
| cocotb | 2.1.0 |
| pyserial | 3.5 |
| Git | 2.56.0.windows.4 |

## Notes
- Use `verilator_bin`. The plain `verilator` command is a Perl script, and Perl is not installed.
- `nextpnr-gowin` is not in this release. Use `nextpnr-himbaechel`.
- `gowin_pack` warns that Numpy, Msgspec and fastcrc are missing. These are optional speedups.
- In PowerShell 5.1, avoid piping these tools into `Select-Object -First`, which hung twice during install. Redirect to a file instead.
