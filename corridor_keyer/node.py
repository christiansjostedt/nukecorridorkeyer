"""
Nuke node logic for the CorridorKeyer gizmo.

Handles reading pixels from Nuke inputs, running CorridorKey inference,
writing EXR sequences to the cache directory, and wiring Read nodes
inside the gizmo to display results.
"""

import os
import time
import threading

# Enable OpenEXR support in OpenCV (disabled by default in pip builds)
os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"

import numpy as np

try:
    import nuke
    import nuke.executeInMainThread
except ImportError:
    pass

from . import engine


# ---------------------------------------------------------------------------
# In-memory frame cache for live preview
# ---------------------------------------------------------------------------

# { gizmo_name: { frame_int: { "fg": np, "alpha": np, "processed": np } } }
_frame_cache = {}
_live_nodes = set()  # names of gizmos with Live mode enabled
_last_live_frame = {}  # { gizmo_name: last_processed_frame }
_live_processing = False  # guard against re-entrant processing

# Background prefetch
_prefetch_thread = None
_prefetch_lock = threading.Lock()

# Resolution presets: name -> internal processing size
RESOLUTION_PRESETS = {
    "Full (2048)": 2048,
    "Three Quarter (1536)": 1536,
    "Half (1024)": 1024,
    "Quarter (512)": 512,
}


# ---------------------------------------------------------------------------
# Pixel I/O helpers
# ---------------------------------------------------------------------------

def _read_node_pixels(node, channels, frame):
    """
    Read pixel data from a Nuke node using the fastest available method.

    Tries direct scanline reading first, falls back to temp EXR.
    Returns a float32 numpy array of shape (H, W, len(channels)).
    """
    # Method 1: Direct pixel access via node.sample() — no disk I/O
    try:
        width = node.width()
        height = node.height()
        if width > 0 and height > 0:
            # Build a single RGBA sample request
            pixel_data = np.zeros((height, width, len(channels)), dtype=np.float32)
            for ci, ch in enumerate(channels):
                for y in range(height):
                    for x in range(width):
                        pixel_data[y, x, ci] = node.sample(ch, x + 0.5, y + 0.5)
            return pixel_data
    except Exception:
        pass

    # Method 2: Temp EXR (reliable fallback)
    return _node_to_numpy_via_temp(node, channels, frame)


def _node_to_numpy_via_temp(node, channels, frame):
    """
    Read pixels by rendering to a temp EXR and loading with OpenCV/oiio.
    This is the reliable fallback for all Nuke versions.
    """
    import tempfile
    import shutil

    tmp_dir = tempfile.mkdtemp(prefix="ck_nuke_")
    # Nuke on Windows requires forward slashes in file paths
    tmp_path = os.path.join(tmp_dir, "tmp.%04d.exr" % frame).replace("\\", "/")

    try:
        write = nuke.nodes.Write(
            file=tmp_path, file_type="exr", datatype="32 bit float",
        )
        write.setInput(0, node)
        nuke.execute(write, frame, frame)
        nuke.delete(write)

        exr_path = tmp_path.replace("%04d", "%04d" % frame)
        # Resolve back to OS path for file reading
        result = _read_exr(os.path.normpath(exr_path), channels)
    finally:
        # Clean up temp files immediately
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return result


def _read_exr(path, channels):
    """Load an EXR file as a float32 numpy array."""
    try:
        import OpenImageIO as oiio
        inp = oiio.ImageInput.open(path)
        spec = inp.spec()
        pixels = np.frombuffer(inp.read_image("float"), dtype=np.float32)
        pixels = pixels.reshape(spec.height, spec.width, spec.nchannels)
        inp.close()
        # Select requested channel count
        return pixels[:, :, :len(channels)]
    except ImportError:
        pass

    try:
        import cv2
        img = cv2.imread(path, cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
        if img is None:
            raise IOError("Failed to read %s" % path)
        # OpenCV loads BGR
        if img.ndim == 3 and img.shape[2] >= 3:
            img = img[:, :, ::-1]  # BGR -> RGB
        if len(channels) == 1 and img.ndim == 3:
            img = img[:, :, 0:1]
        return img.astype(np.float32)
    except ImportError:
        raise ImportError(
            "Neither OpenImageIO nor OpenCV is available. "
            "Install one of them to enable EXR reading."
        )


def _write_exr(path, image, channel_names=None):
    """Write a float32 numpy array to EXR."""
    # Ensure OS-native path for file I/O
    path = os.path.normpath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    try:
        import OpenImageIO as oiio
        h, w = image.shape[:2]
        nch = image.shape[2] if image.ndim == 3 else 1
        if image.ndim == 2:
            image = image[:, :, np.newaxis]
        spec = oiio.ImageSpec(w, h, nch, "half")
        spec.attribute("compression", "pxr24")
        if channel_names:
            spec.channelnames = channel_names
        out = oiio.ImageOutput.create(path)
        out.open(path, spec)
        out.write_image(image.astype(np.float32))
        out.close()
        return
    except ImportError:
        pass

    try:
        import cv2
        if image.ndim == 3 and image.shape[2] >= 3:
            image = image[:, :, ::-1]  # RGB -> BGR for OpenCV
        cv2.imwrite(path, image.astype(np.float32))
        return
    except ImportError:
        raise ImportError(
            "Neither OpenImageIO nor OpenCV is available for EXR writing."
        )


# ---------------------------------------------------------------------------
# Cache directory
# ---------------------------------------------------------------------------

def _get_cache_dir(gizmo):
    """Return the cache directory for this gizmo's output."""
    custom = gizmo.knob("cache_dir").value()
    if custom and custom.strip():
        return custom.strip()

    # Default: next to the nuke script
    import tempfile
    script_dir = os.path.dirname(nuke.root().name()) or tempfile.gettempdir()
    node_name = gizmo.name()
    return os.path.join(script_dir, "corridor_keyer_cache", node_name)


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process_frames(gizmo):
    """
    Process the selected frame range through CorridorKey.
    Called from the gizmo's 'Process' button.
    """
    # Validate inputs
    plate_input = gizmo.input(0)
    hint_input = gizmo.input(1)

    if plate_input is None:
        nuke.message("CorridorKeyer: Connect a plate to input 1 (left).")
        return
    if hint_input is None:
        nuke.message(
            "CorridorKeyer: Connect a coarse alpha/matte to input 2 (right).\n"
            "Tip: Use a Keylight, Primatte, or IBKGizmo for a rough key."
        )
        return

    # Read knob values
    first = int(gizmo.knob("frame_range_first").value())
    last = int(gizmo.knob("frame_range_last").value())
    input_linear = gizmo.knob("input_colorspace").value() == "Linear"
    img_size = _get_processing_resolution(gizmo)

    cache_dir = _get_cache_dir(gizmo)
    fg_dir = os.path.join(cache_dir, "FG")
    alpha_dir = os.path.join(cache_dir, "Matte")
    comp_dir = os.path.join(cache_dir, "Processed")

    os.makedirs(fg_dir, exist_ok=True)
    os.makedirs(alpha_dir, exist_ok=True)
    os.makedirs(comp_dir, exist_ok=True)

    total = last - first + 1
    task = nuke.ProgressTask("CorridorKeyer")
    eng = engine.get_engine(img_size=img_size)

    try:
        for i, frame in enumerate(range(first, last + 1)):
            if task.isCancelled():
                nuke.message("CorridorKeyer: Cancelled by user.")
                return

            task.setMessage("Processing frame %d / %d" % (i + 1, total))
            task.setProgress(int(100.0 * i / total))

            # Read plate RGB
            rgb = _read_input_rgb(plate_input, frame)

            if rgb is None:
                nuke.warning("CorridorKeyer: Skipping frame %d (read error)" % frame)
                continue

            # Read alpha hint
            alpha_hint = _read_input_alpha(hint_input, frame)

            if alpha_hint is None:
                nuke.warning("CorridorKeyer: Skipping frame %d (hint error)" % frame)
                continue

            # Resize alpha hint to match plate if needed
            if alpha_hint.shape[:2] != rgb.shape[:2]:
                import cv2
                alpha_hint = cv2.resize(
                    alpha_hint, (rgb.shape[1], rgb.shape[0]),
                    interpolation=cv2.INTER_LANCZOS4,
                )

            # Run inference
            result = eng.process_frame(
                rgb, alpha_hint, input_is_linear=input_linear
            )

            # Write outputs
            frame_str = "%04d" % frame
            _write_exr(
                os.path.join(fg_dir, "fg.%s.exr" % frame_str),
                result["fg"],
                ["R", "G", "B"],
            )
            _write_exr(
                os.path.join(alpha_dir, "matte.%s.exr" % frame_str),
                result["alpha"],
                ["A"],
            )
            _write_exr(
                os.path.join(comp_dir, "processed.%s.exr" % frame_str),
                result["processed"],
                ["R", "G", "B", "A"],
            )

        task.setProgress(100)
        task.setMessage("Done")

    finally:
        del task

    # Wire up Read nodes inside gizmo
    _update_read_nodes(gizmo, cache_dir, first, last)
    nuke.message("CorridorKeyer: Done! Processed %d frames." % total)


def _read_input_rgb(node, frame):
    """Read RGB from a Nuke node at the given frame."""
    return _node_to_numpy_via_temp(node, ["R", "G", "B"], frame)


def _read_input_alpha(node, frame):
    """Read alpha channel from a Nuke node at the given frame."""
    arr = _node_to_numpy_via_temp(node, ["A"], frame)
    if arr is not None and arr.ndim == 3:
        arr = arr[:, :, 0]
    return arr


# ---------------------------------------------------------------------------
# Internal Read-node wiring
# ---------------------------------------------------------------------------

def _update_read_nodes(gizmo, cache_dir, first, last):
    """Create or update Read nodes inside the gizmo to show results."""
    gizmo.begin()
    try:
        _wire_read(
            gizmo, "ReadFG",
            os.path.join(cache_dir, "FG", "fg.####.exr"),
            first, last,
        )
        _wire_read(
            gizmo, "ReadMatte",
            os.path.join(cache_dir, "Matte", "matte.####.exr"),
            first, last,
        )
        _wire_read(
            gizmo, "ReadProcessed",
            os.path.join(cache_dir, "Processed", "processed.####.exr"),
            first, last,
        )
    finally:
        gizmo.end()


def _wire_read(gizmo, node_name, file_pattern, first, last):
    """Create or update a named Read node inside the gizmo."""
    existing = nuke.toNode(node_name)
    if existing:
        existing.knob("file").setValue(file_pattern)
        existing.knob("first").setValue(first)
        existing.knob("last").setValue(last)
    else:
        read = nuke.nodes.Read(name=node_name, file=file_pattern)
        read.knob("first").setValue(first)
        read.knob("last").setValue(last)
        read.knob("origfirst").setValue(first)
        read.knob("origlast").setValue(last)


# ---------------------------------------------------------------------------
# Utility callbacks
# ---------------------------------------------------------------------------

def on_create(gizmo):
    """Called when the gizmo is created. Sets default frame range."""
    root = nuke.root()
    gizmo.knob("frame_range_first").setValue(root.firstFrame())
    gizmo.knob("frame_range_last").setValue(root.lastFrame())


def clear_cache(gizmo):
    """Delete cached frames for this gizmo."""
    import shutil
    cache_dir = _get_cache_dir(gizmo)
    if os.path.isdir(cache_dir):
        shutil.rmtree(cache_dir)
        nuke.message("CorridorKeyer: Cache cleared.\n%s" % cache_dir)
    else:
        nuke.message("CorridorKeyer: No cache found.")


def release_gpu():
    """Free GPU memory held by the engine."""
    engine.release_engine()
    nuke.message("CorridorKeyer: GPU memory released.")


# ---------------------------------------------------------------------------
# Single-frame processing (current frame)
# ---------------------------------------------------------------------------

def _get_processing_resolution(gizmo):
    """Read the processing resolution from the gizmo knob."""
    try:
        preset = gizmo.knob("processing_res").value()
        return RESOLUTION_PRESETS.get(preset, 2048)
    except Exception:
        return 2048


def _process_single_frame(gizmo, frame):
    """
    Process a single frame and write to cache.
    Returns the result dict or None on failure.
    """
    plate_input = gizmo.input(0)
    hint_input = gizmo.input(1)

    if plate_input is None or hint_input is None:
        return None

    input_linear = gizmo.knob("input_colorspace").value() == "Linear"
    img_size = _get_processing_resolution(gizmo)

    rgb = _read_input_rgb(plate_input, frame)
    if rgb is None:
        return None

    alpha_hint = _read_input_alpha(hint_input, frame)

    if alpha_hint is None:
        return None

    # Resize alpha hint to match plate if needed
    if alpha_hint.shape[:2] != rgb.shape[:2]:
        import cv2
        alpha_hint = cv2.resize(
            alpha_hint, (rgb.shape[1], rgb.shape[0]),
            interpolation=cv2.INTER_LANCZOS4,
        )

    # Get or create engine at the requested resolution
    eng = engine.get_engine(img_size=img_size)
    result = eng.process_frame(rgb, alpha_hint, input_is_linear=input_linear)
    return result




def process_current_frame(gizmo):
    """
    Process only the current viewer frame and write to disk cache.
    Called from the 'Process Current Frame' button.
    """
    plate_input = gizmo.input(0)
    hint_input = gizmo.input(1)

    if plate_input is None:
        nuke.message("CorridorKeyer: Connect a plate to input 1 (left).")
        return
    if hint_input is None:
        nuke.message(
            "CorridorKeyer: Connect a coarse alpha/matte to input 2 (right).\n"
            "Tip: Use a Keylight, Primatte, or IBKGizmo for a rough key."
        )
        return

    frame = nuke.frame()
    cache_dir = _get_cache_dir(gizmo)

    task = nuke.ProgressTask("CorridorKeyer")
    task.setMessage("Processing frame %d" % frame)
    task.setProgress(0)

    try:
        result = _process_single_frame(gizmo, frame)
        if result is None:
            nuke.message("CorridorKeyer: Failed to process frame %d." % frame)
            return

        nuke.tprint("CorridorKeyer: Got result keys: %s" % list(result.keys()))
        for k, v in result.items():
            if hasattr(v, 'shape'):
                nuke.tprint("  %s: shape=%s dtype=%s min=%.4f max=%.4f" % (
                    k, v.shape, v.dtype, v.min(), v.max()))

        # Write to disk
        frame_str = "%04d" % frame
        nuke.tprint("CorridorKeyer: Writing to %s" % cache_dir)
        _write_exr(
            os.path.join(cache_dir, "FG", "fg.%s.exr" % frame_str),
            result["fg"], ["R", "G", "B"],
        )
        _write_exr(
            os.path.join(cache_dir, "Matte", "matte.%s.exr" % frame_str),
            result["alpha"], ["A"],
        )
        _write_exr(
            os.path.join(cache_dir, "Processed", "processed.%s.exr" % frame_str),
            result["processed"], ["R", "G", "B", "A"],
        )

        # Store in memory cache
        node_name = gizmo.name()
        if node_name not in _frame_cache:
            _frame_cache[node_name] = {}
        _frame_cache[node_name][frame] = result

        # Update read nodes to point at cache
        _update_read_nodes(gizmo, cache_dir, frame, frame)

        task.setProgress(100)
    finally:
        del task


# ---------------------------------------------------------------------------
# Live preview mode
# ---------------------------------------------------------------------------

def _live_update_callback():
    """
    Called by nuke.addUpdateUI on every viewer refresh.
    Checks if the frame changed for any live-enabled gizmo and processes it.
    """
    global _live_processing

    if _live_processing:
        return
    if not _live_nodes:
        return

    frame = nuke.frame()

    for node_name in list(_live_nodes):
        gizmo = nuke.toNode(node_name)
        if gizmo is None:
            _live_nodes.discard(node_name)
            continue

        last = _last_live_frame.get(node_name)
        if last == frame:
            continue  # already processed this frame

        # Check memory cache first
        cached = _frame_cache.get(node_name, {}).get(frame)
        if cached is not None:
            _last_live_frame[node_name] = frame
            # Result already on disk from prior processing, just update reads
            cache_dir = _get_cache_dir(gizmo)
            _update_read_nodes(gizmo, cache_dir, frame, frame)
            continue

        # Need to process — do it
        _live_processing = True
        try:
            result = _process_single_frame(gizmo, frame)
            if result is None:
                continue

            cache_dir = _get_cache_dir(gizmo)
            frame_str = "%04d" % frame
            _write_exr(
                os.path.join(cache_dir, "FG", "fg.%s.exr" % frame_str),
                result["fg"], ["R", "G", "B"],
            )
            _write_exr(
                os.path.join(cache_dir, "Matte", "matte.%s.exr" % frame_str),
                result["alpha"], ["A"],
            )
            _write_exr(
                os.path.join(cache_dir, "Processed", "processed.%s.exr" % frame_str),
                result["processed"], ["R", "G", "B", "A"],
            )

            if node_name not in _frame_cache:
                _frame_cache[node_name] = {}
            _frame_cache[node_name][frame] = result
            _last_live_frame[node_name] = frame

            _update_read_nodes(gizmo, cache_dir, frame, frame)

            # Kick off background prefetch for next frames
            try:
                prefetch_count = int(gizmo.knob("prefetch_frames").value())
                if prefetch_count > 0:
                    _prefetch_adjacent_frames(gizmo, frame, prefetch_count)
            except Exception:
                pass

        except Exception as e:
            nuke.warning("CorridorKeyer Live: %s" % str(e))
        finally:
            _live_processing = False


_live_callback_registered = False


def toggle_live(gizmo):
    """Toggle live preview mode for this gizmo."""
    global _live_callback_registered

    node_name = gizmo.name()
    is_live = gizmo.knob("live_preview").value()

    if is_live:
        # Validate inputs before enabling
        if gizmo.input(0) is None or gizmo.input(1) is None:
            gizmo.knob("live_preview").setValue(False)
            nuke.message(
                "CorridorKeyer: Connect both inputs before enabling Live mode."
            )
            return

        _live_nodes.add(node_name)

        # Register the updateUI callback once
        if not _live_callback_registered:
            nuke.addUpdateUI(_live_update_callback)
            _live_callback_registered = True

        # Process current frame immediately
        process_current_frame(gizmo)
    else:
        _live_nodes.discard(node_name)
        _last_live_frame.pop(node_name, None)


def clear_memory_cache(gizmo):
    """Clear the in-memory frame cache for this gizmo."""
    node_name = gizmo.name()
    _frame_cache.pop(node_name, None)
    _last_live_frame.pop(node_name, None)


# ---------------------------------------------------------------------------
# Background prefetch
# ---------------------------------------------------------------------------

def _prefetch_adjacent_frames(gizmo, current_frame, count=2):
    """
    Process frames adjacent to the current frame in a background thread.
    Pre-caches the next `count` frames so scrubbing forward feels instant.
    """
    global _prefetch_thread

    node_name = gizmo.name()
    cache_dir = _get_cache_dir(gizmo)
    frames_to_fetch = []

    for offset in range(1, count + 1):
        fwd = current_frame + offset
        if fwd not in _frame_cache.get(node_name, {}):
            frames_to_fetch.append(fwd)

    if not frames_to_fetch:
        return

    def _do_prefetch():
        for frame in frames_to_fetch:
            with _prefetch_lock:
                # Check again in case it was processed while waiting
                if frame in _frame_cache.get(node_name, {}):
                    continue

                try:
                    result = _process_single_frame(gizmo, frame)
                    if result is None:
                        continue

                    frame_str = "%04d" % frame
                    _write_exr(
                        os.path.join(cache_dir, "FG", "fg.%s.exr" % frame_str),
                        result["fg"], ["R", "G", "B"],
                    )
                    _write_exr(
                        os.path.join(cache_dir, "Matte", "matte.%s.exr" % frame_str),
                        result["alpha"], ["A"],
                    )
                    _write_exr(
                        os.path.join(cache_dir, "Processed", "processed.%s.exr" % frame_str),
                        result["processed"], ["R", "G", "B", "A"],
                    )

                    if node_name not in _frame_cache:
                        _frame_cache[node_name] = {}
                    _frame_cache[node_name][frame] = result

                except Exception as e:
                    nuke.tprint("CorridorKeyer prefetch: %s" % str(e))

    # Only one prefetch thread at a time
    if _prefetch_thread is not None and _prefetch_thread.is_alive():
        return

    _prefetch_thread = threading.Thread(target=_do_prefetch, daemon=True)
    _prefetch_thread.start()
