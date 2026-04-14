#!/usr/bin/env python3
r"""
Quick diagnostic to verify torch loads correctly.
Run with the same Python that Nuke uses, or with any Python that has
the CorridorKeyer dependencies installed.

Usage:
    python test_torch.py
    # or with Nuke's Python:
    "C:\Program Files\Nuke15.2v4\python.exe" test_torch.py
"""

import os
import sys
import platform

print("=" * 60)
print("  CorridorKeyer Torch Diagnostic")
print("=" * 60)
print(f"  Python:   {sys.version}")
print(f"  Platform: {platform.system()} {platform.machine()}")
print(f"  Exe:      {sys.executable}")
print()

# 1. Check sys.path for site-packages
print("[1/6] Site-packages on sys.path:")
for p in sys.path:
    if "site-packages" in p or "Python3" in p:
        exists = "OK" if os.path.isdir(p) else "MISSING"
        print(f"  [{exists}] {p}")
print()

# 2. Check numpy
print("[2/6] numpy:", end=" ")
try:
    import numpy as np
    print(f"OK — {np.__version__} from {np.__file__}")
except Exception as e:
    print(f"FAILED — {e}")
    print("\n  Cannot continue without numpy.")
    sys.exit(1)

# 3. Check OpenCV EXR support
print("[3/6] opencv:", end=" ")
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
try:
    import cv2
    print(f"OK — {cv2.__version__}")
except Exception as e:
    print(f"FAILED — {e}")

# 4. Find torch DLLs and try preloading
print("[4/6] torch DLL preload:", end=" ")
if platform.system() == "Windows":
    import ctypes
    torch_lib = None
    for sp in sys.path:
        candidate = os.path.join(sp, "torch", "lib")
        if os.path.isdir(candidate):
            torch_lib = candidate
            break

    if torch_lib:
        print(f"\n  Found torch/lib at: {torch_lib}")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(torch_lib)
        os.environ["PATH"] = torch_lib + os.pathsep + os.environ.get("PATH", "")

        # Try loading individual DLLs
        dlls = ["asmjit.dll", "c10.dll", "torch_cpu.dll", "fbgemm.dll", "torch_python.dll"]
        for dll_name in dlls:
            dll_path = os.path.join(torch_lib, dll_name)
            if os.path.isfile(dll_path):
                try:
                    ctypes.CDLL(dll_path)
                    print(f"  [OK]     {dll_name}")
                except OSError as e:
                    print(f"  [FAILED] {dll_name} — {e}")
            else:
                print(f"  [SKIP]   {dll_name} — not found")
    else:
        print("torch/lib not found on sys.path")
else:
    print("skipped (not Windows)")

# 5. Import torch
print("\n[5/6] import torch:", end=" ")
try:
    import torch
    cuda_status = "CUDA available" if torch.cuda.is_available() else "CPU only"
    print(f"OK — {torch.__version__} ({cuda_status})")
    if torch.cuda.is_available():
        print(f"  GPU: {torch.cuda.get_device_name(0)}")
except Exception as e:
    print(f"FAILED — {e}")
    print("\n  This is the error Nuke would hit. Fix this first.")
    sys.exit(1)

# 6. Check CorridorKey
print("[6/6] CorridorKey:", end=" ")
ck_path = os.environ.get("CORRIDORKEY_PATH", "")
if ck_path:
    if ck_path not in sys.path:
        sys.path.insert(0, ck_path)
    try:
        from CorridorKeyModule import CorridorKeyEngine
        print(f"OK — found at {ck_path}")
    except ImportError as e:
        print(f"importable but missing module — {e}")
else:
    # Try finding it relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    for candidate in [
        os.path.join(parent_dir, "CorridorKey"),
        os.path.join(script_dir, "..", "CorridorKey"),
    ]:
        if os.path.isdir(candidate):
            ck_path = candidate
            break
    if ck_path:
        sys.path.insert(0, ck_path)
        try:
            from CorridorKeyModule import CorridorKeyEngine
            print(f"OK — found at {ck_path}")
        except ImportError as e:
            print(f"found dir but import failed — {e}")
    else:
        print("CORRIDORKEY_PATH not set, skipped")

print()
print("=" * 60)
print("  All critical checks passed!" if "torch" in sys.modules else "  Some checks failed.")
print("=" * 60)
