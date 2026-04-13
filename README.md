# CorridorKeyer for Nuke

Nuke integration for [Corridor Digital's AI green screen keyer](https://github.com/nikopueringer/CorridorKey). Produces physically accurate foreground colour reconstruction and clean linear alpha — not just a matte, but true colour unmixing for motion blur, hair, and semi-transparent edges.

## Requirements

- **Nuke** 13+ (Python 3)
- **CorridorKey** — clone from [github.com/nikopueringer/CorridorKey](https://github.com/nikopueringer/CorridorKey)
- **PyTorch** 2.8+ with CUDA (or MPS on Apple Silicon)
- **OpenImageIO** (ships with Nuke) or **OpenCV**

## Installation

### 1. Install CorridorKey

```bash
git clone https://github.com/nikopueringer/CorridorKey.git
cd CorridorKey
pip install -e .
# or: uv pip install -e .
```

The model checkpoint (`CorridorKey.pth`) will auto-download from HuggingFace on first run, or you can place it manually in `CorridorKey/models/`.

### 2. Install this plugin

Clone this repo somewhere on disk:

```bash
git clone https://github.com/christiansjostedt/nukecorridorkeyer.git
```

Add the plugin path to your `~/.nuke/init.py`:

```python
import os
nuke.pluginAddPath("/path/to/nukecorridorkeyer")

# Tell the plugin where CorridorKey lives:
os.environ["CORRIDORKEY_PATH"] = "/path/to/CorridorKey"
```

Or set the environment variables before launching Nuke:

```bash
export CORRIDORKEY_PATH="/path/to/CorridorKey"
export NUKE_PATH="/path/to/nukecorridorkeyer:$NUKE_PATH"
```

### 3. Verify

Launch Nuke. You should see **CorridorKeyer** in the toolbar and under the Keyer menu.

## Usage

1. **Create the node** — Tab-search "CorridorKeyer" or find it in the toolbar
2. **Connect inputs**:
   - **Input 1 (left)** — Your green screen plate
   - **Input 2 (right)** — A coarse alpha hint (rough matte from Keylight, Primatte, IBKGizmo, or any roto)
3. **Set the frame range** and colorspace (Linear for EXR, sRGB for jpg/png plates)
4. **Click "Process Frames"** — runs inference and caches EXR results to disk
5. **Select output** — Switch between Processed (RGBA), Foreground, Matte, or Passthrough

### Generating a good alpha hint

The alpha hint doesn't need to be perfect — that's the whole point. A quick Keylight with default settings works well. The AI handles the hard edges, hair, and transparency. Tips:

- **Keylight** → pick the green, leave everything else at defaults
- **Primatte** → auto-compute is fine
- **IBKGizmo** → works great for uneven screens
- **Roto** → a rough hand-drawn shape also works

### Output modes

| Mode | Description |
|------|-------------|
| **Processed (RGBA)** | Premultiplied RGBA, linear. Ready to comp over a background |
| **Foreground (RGB)** | Straight (un-premultiplied) foreground colour in sRGB gamut. Apply a colourspace conversion for linear workflows |
| **Matte (Alpha)** | Clean linear alpha channel |
| **Plate (Passthrough)** | The original plate, unmodified |

### Cache management

Processed frames are cached as EXR sequences next to your Nuke script (or in a custom directory you specify). Use **Clear Cache** to free disk space when done.

### GPU memory

The model uses ~6-8 GB VRAM. Click **Release GPU Memory** when you're done processing to free it for other tools.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `CORRIDORKEY_PATH` | Path to the cloned CorridorKey repository |
| `CORRIDORKEY_MODEL` | Override path to `CorridorKey.pth` checkpoint |
| `CORRIDORKEY_DEVICE` | Force device: `cuda`, `mps`, or `cpu` |

## Project Structure

```
nukecorridorkeyer/
├── init.py                  # Nuke plugin bootstrapping
├── menu.py                  # Toolbar and menu entries
├── corridor_keyer/
│   ├── __init__.py
│   ├── engine.py            # Bridge to CorridorKeyEngine
│   └── node.py              # Frame processing and Nuke I/O
├── gizmos/
│   └── CorridorKeyer.gizmo  # Artist-facing node
└── icons/
    └── (place corridor_keyer.png here)
```

## License

This Nuke integration wrapper is MIT licensed. The underlying CorridorKey model and code are licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) — non-commercial use only. Contact Corridor Digital for commercial licensing.
