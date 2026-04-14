"""
Bridge between Nuke and the CorridorKey inference engine.

Expects the CorridorKey repository to be installed and importable.
Set CORRIDORKEY_PATH in your environment or Nuke's init.py to point
to the cloned CorridorKey repo if it is not on sys.path.
"""

import os
import platform
import sys
import ctypes
import types

# Nuke's Python is missing some standard library C extensions (like _lzma)
# that torchvision imports. Provide stubs so imports don't fail.
for _missing_mod in ["_lzma", "lzma"]:
    if _missing_mod not in sys.modules:
        try:
            __import__(_missing_mod)
        except (ImportError, ModuleNotFoundError):
            _stub = types.ModuleType(_missing_mod)
            # torchvision.datasets.utils references lzma.open
            _stub.open = None
            _stub.LZMAFile = None
            _stub.LZMACompressor = None
            _stub.LZMADecompressor = None
            _stub.LZMAError = type("LZMAError", (Exception,), {})
            _stub.FORMAT_AUTO = 0
            _stub.FORMAT_XZ = 1
            _stub.FORMAT_ALONE = 2
            _stub.FORMAT_RAW = 3
            _stub.CHECK_NONE = 0
            _stub.CHECK_CRC32 = 1
            _stub.CHECK_CRC64 = 4
            _stub.CHECK_SHA256 = 10
            sys.modules[_missing_mod] = _stub

import numpy as np


def _preload_torch_dlls():
    """
    Pre-load torch DLLs on Windows to work around Nuke's Python
    not finding them through standard DLL search paths.
    """
    if platform.system() != "Windows":
        return

    torch_lib = None
    for sp in sys.path:
        candidate = os.path.join(sp, "torch", "lib")
        if os.path.isdir(candidate):
            torch_lib = candidate
            break
    if not torch_lib:
        return

    # Register DLL directory (Python 3.8+)
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(torch_lib)
    os.environ["PATH"] = torch_lib + os.pathsep + os.environ.get("PATH", "")

    # Pre-load DLLs in dependency order to avoid "procedure not found" errors.
    # torch ships these DLLs and they must be loaded before fbgemm.dll.
    load_order = [
        "asmjit.dll",
        "c10.dll",
        "caffe2_nvrtc.dll",
        "shm.dll",
        "torch_cpu.dll",
        "torch_python.dll",
        "fbgemm.dll",
        "torch_cuda.dll",
    ]
    for dll_name in load_order:
        dll_path = os.path.join(torch_lib, dll_name)
        if os.path.isfile(dll_path):
            try:
                ctypes.CDLL(dll_path)
            except OSError:
                pass  # some DLLs may not load standalone, that's OK


_preload_torch_dlls()

_engine_instance = None
_engine_img_size = None


def _ensure_corridorkey_on_path():
    """Add CorridorKey repo to sys.path if CORRIDORKEY_PATH is set."""
    ck_path = os.environ.get("CORRIDORKEY_PATH", "")
    if ck_path and ck_path not in sys.path:
        sys.path.insert(0, ck_path)


def get_engine(checkpoint_path=None, device=None, img_size=2048):
    """
    Return a cached CorridorKeyEngine instance.

    Parameters
    ----------
    checkpoint_path : str or None
        Path to CorridorKey.pth. If None, uses CORRIDORKEY_MODEL env var
        or falls back to <CORRIDORKEY_PATH>/models/CorridorKey.pth.
    device : str or None
        'cuda', 'mps', or 'cpu'. Auto-detected if None.
    img_size : int
        Internal processing resolution (default 2048).
    """
    global _engine_instance, _engine_img_size

    # Reuse existing engine if resolution matches
    if _engine_instance is not None and _engine_img_size == img_size:
        return _engine_instance

    # Resolution changed — release old engine first
    if _engine_instance is not None:
        release_engine()

    _ensure_corridorkey_on_path()

    try:
        from CorridorKeyModule import CorridorKeyEngine
    except ImportError:
        raise ImportError(
            "Cannot import CorridorKeyModule. "
            "Set the CORRIDORKEY_PATH environment variable to the root of "
            "the cloned CorridorKey repository, or install it with pip."
        )

    if checkpoint_path is None:
        checkpoint_path = os.environ.get("CORRIDORKEY_MODEL", "")
        if not checkpoint_path:
            ck_path = os.environ.get("CORRIDORKEY_PATH", "")
            checkpoint_path = os.path.join(ck_path, "models", "CorridorKey.pth")

    if device is None:
        device = os.environ.get("CORRIDORKEY_DEVICE", "").lower()
        if not device:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"

    _engine_instance = CorridorKeyEngine(
        checkpoint_path=checkpoint_path,
        device=device,
        img_size=img_size,
    )
    _engine_img_size = img_size
    return _engine_instance


def release_engine():
    """Free GPU memory by releasing the cached engine."""
    global _engine_instance
    if _engine_instance is not None:
        del _engine_instance
        _engine_instance = None
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def process_frame(rgb, alpha_hint, input_is_linear=True):
    """
    Run CorridorKey inference on a single frame.

    Parameters
    ----------
    rgb : numpy.ndarray
        Float32 array of shape (H, W, 3), range [0, 1].
    alpha_hint : numpy.ndarray
        Float32 array of shape (H, W), range [0, 1]. A coarse matte.
    input_is_linear : bool
        True if rgb is in linear light (standard for Nuke/EXR workflows).

    Returns
    -------
    dict with keys:
        'fg'    : (H, W, 3) float32 — straight foreground colour (sRGB gamut)
        'alpha' : (H, W)    float32 — linear alpha
        'processed' : (H, W, 4) float32 — premultiplied RGBA (linear)
    """
    engine = get_engine()
    result = engine.process_frame(rgb, alpha_hint, input_is_linear=input_is_linear)
    return result
