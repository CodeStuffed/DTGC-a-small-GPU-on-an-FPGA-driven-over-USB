#!/usr/bin/env python3
"""Usage: python sw/d3d9/build.py

Builds build/d3d9/x64/ and build/d3d9/x86/, each with d3d9.dll (the DTGC layer) and test_app.exe. A program
must use the DLL of its own bitness; older games are mostly 32 bit (x86). Needs Visual Studio with C++ tools
and a Windows SDK. The code for methods the layer does not support is written here from the SDK's d3d9.h.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = ROOT / "build" / "d3d9"
SDK_INCLUDE = Path(r"C:\Program Files (x86)\Windows Kits\10\Include")
INTERFACES = ["IDirect3DDevice9", "IDirect3DVertexBuffer9", "IDirect3DIndexBuffer9", "IDirect3DTexture9"]
SKIP = {"QueryInterface", "AddRef", "Release"}


def find_vcvarsall():
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    if vswhere.exists():
        found = subprocess.run([str(vswhere), "-latest", "-products", "*", "-property", "installationPath"],
                               capture_output=True, text=True).stdout.strip()
        path = Path(found) / "VC/Auxiliary/Build/vcvarsall.bat"
        if found and path.exists():
            return path
    raise SystemExit("Visual Studio with C++ tools was not found")


def write_stubs():
    """Every method of each interface that dtgc_d3d9.cpp does not write itself gets a body that refuses the call."""
    versions = sorted(SDK_INCLUDE.iterdir(), key=lambda p: [int(n) for n in p.name.split(".")])
    header = (versions[-1] / "shared" / "d3d9.h").read_text(encoding="latin-1")
    source = (HERE / "dtgc_d3d9.cpp").read_text(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    classes = {"IDirect3DDevice9": "class Device", "IDirect3DVertexBuffer9": "class VertexBuffer",
               "IDirect3DIndexBuffer9": "class IndexBuffer", "IDirect3DTexture9": "class Texture"}
    for interface in INTERFACES:
        start = header.index(f"DECLARE_INTERFACE_({interface},")
        end = header.index("};", start)
        body = re.sub(r"#ifdef D3D_DEBUG_INFO.*?#endif", "", header[start:end], flags=re.S)
        at = source.index(classes[interface] + " :")
        finish = source.find("\nclass ", at + 10)
        written = source[at:finish if finish > 0 else len(source)]
        lines = []
        for kind, returns, name, args in re.findall(r"STDMETHOD(_?)\(\s*(?:([\w ]+\*?)\s*,\s*)?(\w+)\s*\)\s*\((.*?)\)\s*PURE\s*;", body, flags=re.S):
            if name in SKIP or re.search(rf"\b{name}\(", written):
                continue
            args = " ".join(args.split())
            args = re.sub(r"^THIS_?\s*", "", args)
            names = re.sub(r"\[[^\]]*\]", "", args)
            head = f"STDMETHODIMP_({returns.strip()})" if kind else "STDMETHODIMP"
            result = {"void": "", "": "return D3DERR_INVALIDCALL;"}.get(returns.strip() if kind else "", "return {};")
            lines.append(f"{head} {name}({names}) override {{ note_unsupported(\"{name}\"); {result} }}")
        (OUT / f"{interface}_stubs.inc").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{interface}: {len(lines)} methods refuse the call")


def build(vcvars, arch):
    folder = OUT / arch
    folder.mkdir(parents=True, exist_ok=True)
    flags = "/nologo /std:c++17 /EHsc /O2 /W3 /MT /DUNICODE /D_UNICODE /DWIN32_LEAN_AND_MEAN /DNOMINMAX"
    script = folder / "build.bat"
    script.write_text(
        f'@call "{vcvars}" {arch} >nul\r\n'
        f'cd /d "{folder}"\r\n'
        f'cl {flags} /LD /I"{OUT}" "{HERE / "dtgc_d3d9.cpp"}" /Fe:d3d9.dll /link /DEF:"{HERE / "d3d9.def"}" ws2_32.lib user32.lib dxguid.lib || exit /b 1\r\n'
        f'cl {flags} "{HERE / "test_app.cpp"}" /Fe:test_app.exe /link user32.lib gdi32.lib d3d9.lib || exit /b 1\r\n')
    result = subprocess.run(["cmd", "/c", str(script)], capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-6000:])
        print(result.stderr[-1000:])
        sys.exit(f"{arch} build failed")
    print(f"{arch}: {folder / 'd3d9.dll'} and test_app.exe")


def main():
    vcvars = find_vcvarsall()
    write_stubs()
    for arch in ("x64", "x86"):
        build(vcvars, arch)


if __name__ == "__main__":
    main()
