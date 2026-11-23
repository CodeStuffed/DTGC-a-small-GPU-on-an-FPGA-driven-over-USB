#!/usr/bin/env python3
"""Usage: python scripts/get_doom.py [--freedoom] [--yes]

Sets up Doom for DTGC. Run it once, yourself: it fetches other people's code from the internet, so it says what it will
fetch and waits for you to type y (--yes skips the question).

  1. Fetches the source of doomgeneric, a portable version of the Doom engine, with git, into build/doom/doomgeneric.
     From https://github.com/ozkl/doomgeneric . Licence: GNU GPL version 2.
  2. Compiles it together with our own sw/doom/doomgeneric_dtgc.c into build/doom/dtgc_doom.exe. Needs a C compiler:
     Visual Studio with C++ tools on Windows, cc on Linux (the Linux build has not been tried).
  3. With --freedoom: downloads Freedoom 0.13.0, a free set of levels and pictures the engine can play, and puts
     freedoom1.wad and freedoom2.wad in build/doom. 24,143,781 bytes, from the Freedoom project's releases on GitHub.
     Without it, put a game file of your own there, such as doom1.wad (the shareware Doom) or doom.wad.

Then play with: python -m sw.dtgc doom      (docs/doom.md)

Only step 2 has been tried here, and only against a stand-in for the engine (sw/tests/doom_standin). The real engine
has not been fetched or built on this project's PC, so if the compiler stops, copy what it prints into docs/test-log.md.
"""
import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOOM = ROOT / "build" / "doom"
ENGINE_URL = "https://github.com/ozkl/doomgeneric"
FREEDOOM_URL = "https://github.com/freedoom/freedoom/releases/download/v0.13.0/freedoom-0.13.0.zip"
FREEDOOM_BYTES = 24143781  # as listed by GitHub for that file on 2026-11-11
PLATFORM_FILE = ROOT / "sw" / "doom" / "doomgeneric_dtgc.c"

# The engine's own files, from the list in its Visual Studio project. Its other platform files (SDL, X11, Windows
# window, sound through SDL or Allegro) are left out: ours takes their place, and there is no sound.
ENGINE_FILES = """am_map doomdef doomgeneric doomstat dstrings dummy d_event d_items d_iwad d_loop d_main d_mode d_net f_finale
f_wipe gusconf g_game hu_lib hu_stuff icon info i_cdmus i_endoom i_input i_joystick i_scale i_sound i_system i_timer i_video
memio m_argv m_bbox m_cheat m_config m_controls m_fixed m_menu m_misc m_random p_ceilng p_doors p_enemy p_floor p_inter
p_lights p_map p_maputl p_mobj p_plats p_pspr p_saveg p_setup p_sight p_spec p_switch p_telept p_tick p_user r_bsp r_data
r_draw r_main r_plane r_segs r_sky r_things sha1 sounds statdump st_lib st_stuff s_sound tables v_video wi_stuff
w_checksum w_file w_file_stdc w_main w_wad z_zone""".split()

SIZE = ("DOOMGENERIC_RESX=320", "DOOMGENERIC_RESY=200")


def find_vcvarsall():
    """Visual Studio's script that puts its compiler on the path, or None."""
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    if not vswhere.exists():
        return None
    found = subprocess.run([str(vswhere), "-latest", "-products", "*", "-property", "installationPath"],
                           capture_output=True, text=True).stdout.strip()
    path = Path(found) / "VC/Auxiliary/Build/vcvarsall.bat"
    return path if found and path.exists() else None


def compile_engine(sources, include, program, indexed=True):
    """Compiles the C files into one program. indexed asks the engine for one byte per pixel (CMAP256).

    Returns (True, "") or (False, what the compiler printed).
    """
    work = program.parent / "obj"
    work.mkdir(parents=True, exist_ok=True)
    defines = [*SIZE, *(["CMAP256"] if indexed else [])]
    if sys.platform == "win32":
        vcvarsall = find_vcvarsall()
        if not vcvarsall:
            return False, "Visual Studio with C++ tools was not found."
        options = ["/nologo", "/O2", "/W1", "/D_CRT_SECURE_NO_WARNINGS", "/DNDEBUG", "/D_CONSOLE", *(f"/D{d}" for d in defines),
                   f'/I"{include}"', f'/Fo"{work}\\\\"', f'/Fe"{program}"']
        (work / "files.rsp").write_text("\n".join([*options, *(f'"{s}"' for s in sources), "/link", "ws2_32.lib", "user32.lib"]))
        script = work / "build.bat"
        script.write_text(f'@call "{vcvarsall}" x64 >nul\r\ncl @"{work / "files.rsp"}"\r\n')
        command = ["cmd", "/c", str(script)]
    else:
        compiler = shutil.which("cc") or shutil.which("gcc")
        if not compiler:
            return False, "No C compiler (cc) was found."
        command = [compiler, "-O2", *(f"-D{d}" for d in defines), f"-I{include}", *map(str, sources), "-o", str(program), "-lm"]
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    if result.returncode == 0 and program.exists():
        return True, ""
    return False, (result.stdout + result.stderr).strip()


def program_name():
    return "dtgc_doom.exe" if sys.platform == "win32" else "dtgc_doom"


def fetch_engine(folder):
    if (folder / "doomgeneric" / "doomgeneric.h").exists():
        print(f"The engine's source is already in {folder}.")
        return
    git = shutil.which("git") or (r"C:\Program Files\Git\cmd\git.exe" if Path(r"C:\Program Files\Git\cmd\git.exe").exists() else None)
    if not git:
        sys.exit("git was not found. Install Git, or download the source from " + ENGINE_URL + " and unpack it to " + str(folder))
    subprocess.run([git, "clone", "--depth", "1", ENGINE_URL, str(folder)], check=True)


def build_engine(folder):
    source_folder = folder / "doomgeneric"
    sources = [source_folder / f"{name}.c" for name in ENGINE_FILES]
    missing = [path.name for path in sources if not path.exists()]
    if missing:
        print("These files from the list are not in the engine's source any more, so they are left out: " + ", ".join(missing))
    sources = [path for path in sources if path.exists()] + [PLATFORM_FILE]
    program = DOOM / program_name()
    print(f"Compiling {len(sources)} files. This takes a minute or so.")
    ok, text = compile_engine(sources, source_folder, program)
    if not ok:
        print("The build with one byte per pixel stopped:\n" + text[-3000:])
        print("\nTrying the plain build, which works with fewer colours.")
        ok, text = compile_engine(sources, source_folder, program, indexed=False)
        if not ok:
            sys.exit("That stopped too:\n" + text[-3000:] + "\n\nCopy this into docs/test-log.md.")
        print("Built with full-colour frames cut down to DTGC's 256 built-in colours. The picture will look coarser.")
    print(f"Built {program}")


def fetch_freedoom():
    wanted = ("freedoom1.wad", "freedoom2.wad")
    if all((DOOM / name).exists() for name in wanted):
        print("Freedoom is already in build/doom.")
        return
    archive = DOOM / "freedoom-0.13.0.zip"
    print(f"Downloading {FREEDOOM_URL}")
    with urllib.request.urlopen(FREEDOOM_URL) as response, open(archive, "wb") as out:
        shutil.copyfileobj(response, out)
    if archive.stat().st_size != FREEDOOM_BYTES:
        sys.exit(f"The download is {archive.stat().st_size} bytes, not the {FREEDOOM_BYTES} expected. It is left at {archive} unopened.")
    with zipfile.ZipFile(archive) as packed:
        for entry in packed.namelist():
            name = Path(entry).name.lower()
            if name in wanted or name.startswith("copying"):
                (DOOM / name).write_bytes(packed.read(entry))
                print(f"  took {name}")
    if not (DOOM / "freedoom1.wad").exists():
        sys.exit(f"freedoom1.wad was not inside {archive}. Open it by hand and copy the .wad files to {DOOM}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--freedoom", action="store_true", help="also download the free game files")
    parser.add_argument("--yes", action="store_true", help="do not ask before fetching")
    args = parser.parse_args()
    folder = DOOM / "doomgeneric"
    print("This will fetch from the internet:")
    print(f"  the source of the Doom engine, from {ENGINE_URL} (GNU GPL version 2), into {folder}")
    if args.freedoom:
        print(f"  Freedoom 0.13.0, {FREEDOOM_BYTES:,} bytes, from {FREEDOOM_URL}")
    print("and compile the engine on this PC.")
    if not args.yes and input("Type y to go on: ").strip().lower() != "y":
        sys.exit("Stopped. Nothing was fetched.")
    DOOM.mkdir(parents=True, exist_ok=True)
    fetch_engine(folder)
    build_engine(folder)
    if args.freedoom:
        fetch_freedoom()
    wads = sorted(path.name for path in DOOM.glob("*.wad")) + sorted(path.name for path in DOOM.glob("*.WAD"))
    if wads:
        print("Game files in build/doom: " + ", ".join(sorted(set(wads))))
    else:
        print(f"No game file yet. Put a .wad file in {DOOM}, or run this again with --freedoom.")
    print("Play with: python -m sw.dtgc doom")


if __name__ == "__main__":
    main()
