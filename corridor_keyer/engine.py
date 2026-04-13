"""
Bridge between Nuke and the CorridorKey inference engine.

Expects the CorridorKey repository to be installed and importable.
Set CORRIDORKEY_PATH in your environment or Nuke's init.py to point
to the cloned CorridorKey repo if it is not on sys.path.
"""

import os
import sys
import numpy as np

_engine_instance = None


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
    global _engine_instance
    if _engine_instance is not None:
        return _engine_instance

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
