#!/usr/bin/env python3
"""
Cross-platform installer for CorridorKeyer Nuke plugin.

Works on macOS, Linux, and Windows.

Usage:
    python install.py                   # Interactive install
    python install.py --corridorkey /path/to/CorridorKey
    python install.py --nuke-dir /custom/.nuke
    python install.py --uninstall
"""

import argparse
import io
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from urllib.request import urlopen
from urllib.error import URLError


PLUGIN_NAME = "nukecorridorkeyer"
CORRIDORKEY_REPO = "https://github.com/nikopueringer/CorridorKey.git"
CORRIDORKEY_ZIP = "https://github.com/nikopueringer/CorridorKey/archive/refs/heads/main.zip"
INIT_MARKER = "# --- CorridorKeyer plugin path (auto-added by installer) ---"


def get_nuke_dir():
    """Return the default ~/.nuke directory for the current platform."""
    if platform.system() == "Windows":
        # Nuke on Windows uses %USERPROFILE%/.nuke
        return os.path.join(os.environ.get("USERPROFILE", ""), ".nuke")
    else:
        return os.path.expanduser("~/.nuke")


def get_default_corridorkey_dir():
    """Return a sensible default location to clone CorridorKey into."""
    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(plugin_dir), "CorridorKey")


def find_pip():
    """Find pip or pip3 executable."""
    for cmd in ["pip3", "pip", sys.executable + " -m pip"]:
        try:
            subprocess.run(
                cmd.split() + ["--version"],
                capture_output=True, check=True,
            )
            return cmd.split()
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return None


def download_corridorkey_zip(target_dir):
    """Download CorridorKey as a zip archive (no git required)."""
    print(f"  Downloading CorridorKey zip to {target_dir} ...")
    try:
        response = urlopen(CORRIDORKEY_ZIP)
        zip_data = io.BytesIO(response.read())
        with zipfile.ZipFile(zip_data) as zf:
            # The zip contains a top-level folder like "CorridorKey-main/"
            top_dirs = {name.split("/")[0] for name in zf.namelist() if "/" in name}
            if len(top_dirs) == 1:
                zip_root = top_dirs.pop()
            else:
                zip_root = None

            os.makedirs(target_dir, exist_ok=True)
            for member in zf.namelist():
                # Strip the top-level directory from the zip
                if zip_root and member.startswith(zip_root + "/"):
                    rel_path = member[len(zip_root) + 1:]
                else:
                    rel_path = member
                if not rel_path:
                    continue

                dest = os.path.join(target_dir, rel_path)
                if member.endswith("/"):
                    os.makedirs(dest, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with zf.open(member) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        return True
    except (URLError, OSError, zipfile.BadZipFile) as e:
        print(f"  ERROR: Failed to download zip: {e}")
        return False


def clone_corridorkey(target_dir):
    """Clone the CorridorKey repo if not already present. Falls back to zip download."""
    if os.path.isdir(os.path.join(target_dir, ".git")):
        print(f"  CorridorKey already cloned at {target_dir}")
        print("  Pulling latest changes...")
        subprocess.run(["git", "pull"], cwd=target_dir, check=False)
        return True

    # Check if already downloaded (without .git, e.g. from zip)
    if os.path.isdir(target_dir) and os.listdir(target_dir):
        print(f"  CorridorKey already present at {target_dir}")
        return True

    print(f"  Cloning CorridorKey to {target_dir} ...")
    try:
        subprocess.run(
            ["git", "clone", CORRIDORKEY_REPO, target_dir],
            check=True,
        )
        return True
    except FileNotFoundError:
        print("  git not found, falling back to zip download...")
        return download_corridorkey_zip(target_dir)
    except subprocess.CalledProcessError as e:
        print(f"  git clone failed ({e}), falling back to zip download...")
        return download_corridorkey_zip(target_dir)


def install_dependencies(corridorkey_dir):
    """Install CorridorKey's Python dependencies."""
    pip = find_pip()
    if pip is None:
        print("  WARNING: pip not found. Install dependencies manually:")
        print(f"    pip install -e {corridorkey_dir}")
        return

    print("  Installing CorridorKey Python dependencies...")
    req_file = os.path.join(corridorkey_dir, "requirements.txt")
    if os.path.exists(req_file):
        subprocess.run(pip + ["install", "-r", req_file], check=False)
    else:
        subprocess.run(pip + ["install", "-e", corridorkey_dir], check=False)


def patch_nuke_init(nuke_dir, plugin_dir, corridorkey_dir):
    """Add plugin path and env var to ~/.nuke/init.py."""
    init_path = os.path.join(nuke_dir, "init.py")

    # Read existing content
    existing = ""
    if os.path.exists(init_path):
        with open(init_path, "r") as f:
            existing = f.read()

    # Remove old entry if present
    if INIT_MARKER in existing:
        lines = existing.splitlines(keepends=True)
        new_lines = []
        skip = False
        for line in lines:
            if INIT_MARKER in line:
                skip = True
                continue
            if skip and line.strip() == "":
                skip = False
                continue
            if skip and (line.startswith("import ") or line.startswith("os.") or line.startswith("nuke.")):
                continue
            skip = False
            new_lines.append(line)
        existing = "".join(new_lines).rstrip("\n")

    # Normalise paths to forward slashes for cross-platform Nuke compatibility
    plugin_dir_escaped = plugin_dir.replace("\\", "/")
    corridorkey_dir_escaped = corridorkey_dir.replace("\\", "/")

    block = f"""
{INIT_MARKER}
import os
os.environ["CORRIDORKEY_PATH"] = r"{corridorkey_dir_escaped}"
nuke.pluginAddPath(r"{plugin_dir_escaped}")
"""

    with open(init_path, "w") as f:
        if existing.strip():
            f.write(existing.rstrip("\n") + "\n")
        f.write(block)

    print(f"  Updated {init_path}")


def remove_nuke_init_entry(nuke_dir):
    """Remove the CorridorKeyer entry from ~/.nuke/init.py."""
    init_path = os.path.join(nuke_dir, "init.py")
    if not os.path.exists(init_path):
        print("  No init.py found, nothing to remove.")
        return

    with open(init_path, "r") as f:
        content = f.read()

    if INIT_MARKER not in content:
        print("  No CorridorKeyer entry found in init.py.")
        return

    lines = content.splitlines(keepends=True)
    new_lines = []
    skip = False
    for line in lines:
        if INIT_MARKER in line:
            skip = True
            continue
        if skip and line.strip() == "":
            skip = False
            continue
        if skip and (line.startswith("import ") or line.startswith("os.") or line.startswith("nuke.")):
            continue
        skip = False
        new_lines.append(line)

    with open(init_path, "w") as f:
        f.write("".join(new_lines))

    print(f"  Cleaned {init_path}")


def print_summary(plugin_dir, corridorkey_dir, nuke_dir):
    """Print post-install summary."""
    print("\n" + "=" * 60)
    print("  CorridorKeyer installed successfully!")
    print("=" * 60)
    print(f"\n  Plugin:      {plugin_dir}")
    print(f"  CorridorKey: {corridorkey_dir}")
    print(f"  Nuke config: {nuke_dir}")
    print("\n  Next steps:")
    print("  1. Launch Nuke")
    print("  2. Find 'CorridorKeyer' in the toolbar or Tab menu")
    print("  3. Connect your plate and a rough alpha hint")
    print("  4. Hit 'Process Current Frame' or enable Live preview")

    system = platform.system()
    if system == "Darwin":
        print("\n  macOS note: MPS (Metal) is auto-detected for Apple Silicon.")
        print("  Set CORRIDORKEY_DEVICE=cpu to force CPU if you hit MPS issues.")
    elif system == "Windows":
        print("\n  Windows note: CUDA is auto-detected for NVIDIA GPUs.")
        print("  If Nuke's Python can't find torch, you may need to add your")
        print("  Python site-packages to NUKE_PATH or PYTHONPATH.")

    print()


def main():
    parser = argparse.ArgumentParser(description="Install CorridorKeyer for Nuke")
    parser.add_argument(
        "--corridorkey", "-c",
        help="Path to existing CorridorKey repo (will clone if not provided)",
    )
    parser.add_argument(
        "--nuke-dir", "-n",
        help="Path to .nuke directory (default: auto-detected)",
    )
    parser.add_argument(
        "--skip-deps",
        action="store_true",
        help="Skip installing Python dependencies",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove CorridorKeyer from Nuke config",
    )
    args = parser.parse_args()

    plugin_dir = os.path.dirname(os.path.abspath(__file__))
    nuke_dir = args.nuke_dir or get_nuke_dir()

    # Uninstall
    if args.uninstall:
        print("Uninstalling CorridorKeyer...")
        remove_nuke_init_entry(nuke_dir)
        print("Done. Plugin files were not deleted — remove manually if desired.")
        return

    print("=" * 60)
    print("  CorridorKeyer Installer")
    print(f"  Platform: {platform.system()} {platform.machine()}")
    print("=" * 60)

    # 1. Locate or clone CorridorKey
    corridorkey_dir = args.corridorkey
    clone_ok = True
    if corridorkey_dir:
        corridorkey_dir = os.path.abspath(corridorkey_dir)
        if not os.path.isdir(corridorkey_dir):
            print(f"ERROR: {corridorkey_dir} does not exist.")
            sys.exit(1)
    else:
        corridorkey_dir = get_default_corridorkey_dir()
        print(f"\n[1/3] CorridorKey repository")
        clone_ok = clone_corridorkey(corridorkey_dir)

    # 2. Install dependencies
    if not clone_ok:
        print(f"\n[2/3] Skipping dependency install (CorridorKey not available)")
    elif not args.skip_deps:
        print(f"\n[2/3] Python dependencies")
        install_dependencies(corridorkey_dir)
    else:
        print(f"\n[2/3] Skipping dependency install")

    # 3. Patch Nuke init
    print(f"\n[3/3] Configuring Nuke ({nuke_dir})")
    os.makedirs(nuke_dir, exist_ok=True)
    patch_nuke_init(nuke_dir, plugin_dir, corridorkey_dir)

    if not clone_ok:
        print("\n" + "=" * 60)
        print("  CorridorKeyer partially installed.")
        print("=" * 60)
        print(f"\n  Nuke config was updated, but CorridorKey could not be cloned.")
        print(f"  Make sure 'git' is installed and on your PATH, then either:")
        print(f"    1. Re-run this installer")
        print(f"    2. Clone manually and re-run with --corridorkey <path>:")
        print(f"       git clone {CORRIDORKEY_REPO} {corridorkey_dir}")
        print(f"       python install.py --corridorkey {corridorkey_dir}")
        print()
        sys.exit(1)

    print_summary(plugin_dir, corridorkey_dir, nuke_dir)


if __name__ == "__main__":
    main()
