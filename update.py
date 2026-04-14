#!/usr/bin/env python3
r"""
Update CorridorKeyer plugin files from GitHub.

Downloads the latest code and replaces local files, similar to git pull.
Run this whenever you want to update without re-downloading the zip.

Usage:
    python update.py
"""

import io
import os
import shutil
import ssl
import sys
import zipfile
from urllib.request import urlopen
from urllib.error import URLError

PLUGIN_REPO_ZIP = "https://github.com/christiansjostedt/nukecorridorkeyer/archive/refs/heads/main.zip"

UPDATE_DIRS = ["corridor_keyer", "gizmos", "icons"]
UPDATE_FILES = ["init.py", "menu.py", "test_torch.py", "install.py", "update.py"]


def main():
    plugin_dir = os.path.dirname(os.path.abspath(__file__))

    print("=" * 60)
    print("  CorridorKeyer Updater")
    print("=" * 60)
    print(f"  Plugin dir: {plugin_dir}")
    print(f"  Downloading latest from GitHub...")

    try:
        try:
            response = urlopen(PLUGIN_REPO_ZIP)
        except URLError as e:
            if "CERTIFICATE_VERIFY_FAILED" in str(e):
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                response = urlopen(PLUGIN_REPO_ZIP, context=ctx)
            else:
                raise

        zip_data = io.BytesIO(response.read())
        with zipfile.ZipFile(zip_data) as zf:
            top_dirs = {name.split("/")[0] for name in zf.namelist() if "/" in name}
            zip_root = top_dirs.pop() if len(top_dirs) == 1 else None

            updated = 0
            for member in zf.namelist():
                if zip_root and member.startswith(zip_root + "/"):
                    rel_path = member[len(zip_root) + 1:]
                else:
                    rel_path = member
                if not rel_path:
                    continue

                should_update = False
                for d in UPDATE_DIRS:
                    if rel_path.startswith(d + "/") or rel_path == d:
                        should_update = True
                        break
                if rel_path in UPDATE_FILES:
                    should_update = True

                if not should_update:
                    continue

                dest = os.path.join(plugin_dir, rel_path)
                if member.endswith("/"):
                    os.makedirs(dest, exist_ok=True)
                else:
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with zf.open(member) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    updated += 1

        # Show version
        version_file = os.path.join(plugin_dir, "corridor_keyer", "__init__.py")
        if os.path.exists(version_file):
            with open(version_file, "r") as f:
                for line in f:
                    if "__version__" in line:
                        print(f"  {line.strip()}")
                        break

        print(f"  Updated {updated} files.")
        print()
        print("  To apply changes, restart Nuke.")
        print("  To re-install dependencies, run: python install.py")

    except (URLError, OSError, zipfile.BadZipFile) as e:
        print(f"  ERROR: Update failed: {e}")
        sys.exit(1)

    print()


if __name__ == "__main__":
    main()
