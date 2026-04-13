# CorridorKeyer for Nuke

Nuke integration for [Corridor Digital's AI green screen keyer](https://github.com/nikopueringer/CorridorKey). Produces physically accurate foreground colour reconstruction and clean linear alpha — not just a matte, but true colour unmixing for motion blur, hair, and semi-transparent edges.

## Requirements

- **Nuke** 13+ (Python 3)
- **Python** 3.10+ (for CorridorKey)
- **Git** (for cloning repos)
- **GPU**: NVIDIA with CUDA (Linux/Windows), Apple Silicon with MPS (macOS), or CPU fallback

## Installation

### Quick install (all platforms)

```bash
git clone https://github.com/christiansjostedt/nukecorridorkeyer.git
cd nukecorridorkeyer
python install.py
```

The installer will:
1. Clone the CorridorKey repo (if not already present)
2. Install Python dependencies (PyTorch, timm, etc.)
3. Add the plugin to your `~/.nuke/init.py`

The model checkpoint (`CorridorKey.pth`, ~300 MB) auto-downloads from HuggingFace on first use.

### Install options

```bash
# Point to an existing CorridorKey clone
python install.py --corridorkey /path/to/CorridorKey

# Use a custom .nuke directory
python install.py --nuke-dir /studio/nuke_config

# Skip dependency install (if you manage deps yourself)
python install.py --skip-deps

# Uninstall (removes entry from init.py, keeps files)
python install.py --uninstall
```

### Manual install

If you prefer to set things up by hand:

<details>
<summary>macOS</summary>

```bash
# Clone repos
git clone https://github.com/nikopueringer/CorridorKey.git
git clone https://github.com/christiansjostedt/nukecorridorkeyer.git

# Install dependencies
cd CorridorKey && pip3 install -e . && cd ..

# Add to Nuke — edit ~/.nuke/init.py
echo 'import os' >> ~/.nuke/init.py
echo 'os.environ["CORRIDORKEY_PATH"] = "/path/to/CorridorKey"' >> ~/.nuke/init.py
echo 'nuke.pluginAddPath("/path/to/nukecorridorkeyer")' >> ~/.nuke/init.py
```

Apple Silicon Macs use MPS (Metal) automatically. Force CPU with `CORRIDORKEY_DEVICE=cpu` if you hit MPS issues.
</details>

<details>
<summary>Linux</summary>

```bash
# Clone repos
git clone https://github.com/nikopueringer/CorridorKey.git
git clone https://github.com/christiansjostedt/nukecorridorkeyer.git

# Install dependencies
cd CorridorKey && pip install -e . && cd ..

# Add to Nuke — edit ~/.nuke/init.py
echo 'import os' >> ~/.nuke/init.py
echo 'os.environ["CORRIDORKEY_PATH"] = "/path/to/CorridorKey"' >> ~/.nuke/init.py
echo 'nuke.pluginAddPath("/path/to/nukecorridorkeyer")' >> ~/.nuke/init.py
```

CUDA is auto-detected for NVIDIA GPUs. Ensure your PyTorch install matches your CUDA version.
</details>

<details>
<summary>Windows</summary>

```powershell
# Clone repos
git clone https://github.com/nikopueringer/CorridorKey.git
git clone https://github.com/christiansjostedt/nukecorridorkeyer.git

# Install dependencies
cd CorridorKey
pip install -e .
cd ..

# Add to Nuke — edit %USERPROFILE%\.nuke\init.py
# Add these lines:
#   import os
#   os.environ["CORRIDORKEY_PATH"] = r"C:\path\to\CorridorKey"
#   nuke.pluginAddPath(r"C:\path\to\nukecorridorkeyer")
```

If Nuke's Python can't find `torch`, add your Python `site-packages` to the `PYTHONPATH` environment variable before launching Nuke.
</details>

### Verify

Launch Nuke. You should see **CorridorKeyer** in the toolbar and under the Keyer menu.

## Usage

1. **Create the node** — Tab-search "CorridorKeyer" or find it in the toolbar
2. **Connect inputs**:
   - **Input 1 (left)** — Your green screen plate
   - **Input 2 (right)** — A coarse alpha hint (rough matte from Keylight, Primatte, IBKGizmo, or any roto)
3. **Set the frame range** and colorspace (Linear for EXR, sRGB for jpg/png plates)
4. **Get instant feedback:**
   - **"Process Current Frame"** — processes just the frame you're looking at
   - **"Enable Live"** — auto-processes whenever you scrub to a new frame. Already-processed frames are cached in memory for instant playback
   - **"Process Frames"** — batch-process the full frame range
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

### Live preview

Toggle **"Enable Live"** to automatically key whatever frame you scrub to. The first hit on a new frame takes a moment (inference), but every frame you've already visited is cached in memory and displays instantly. This lets you scrub through a shot and build up a cached preview as you go.

### Cache management

Processed frames are cached both in memory (for live scrubbing) and as EXR sequences on disk next to your Nuke script (or in a custom directory). Use **Clear Cache** to free disk space when done.

### GPU memory

The model uses ~6-8 GB VRAM. Click **Release GPU Memory** when you're done processing to free it for other tools.

## Platform notes

| Platform | GPU | Notes |
|----------|-----|-------|
| **Linux** | NVIDIA (CUDA) | Best performance. Ensure PyTorch CUDA version matches driver. |
| **macOS** | Apple Silicon (MPS) | Auto-detected on M1+. Set `CORRIDORKEY_DEVICE=cpu` as fallback. |
| **Windows** | NVIDIA (CUDA) | May need `PYTHONPATH` set so Nuke finds torch. |
| **Any** | CPU | Works but slow. Force with `CORRIDORKEY_DEVICE=cpu`. |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `CORRIDORKEY_PATH` | Path to the cloned CorridorKey repository |
| `CORRIDORKEY_MODEL` | Override path to `CorridorKey.pth` checkpoint |
| `CORRIDORKEY_DEVICE` | Force device: `cuda`, `mps`, or `cpu` |

## Project Structure

```
nukecorridorkeyer/
├── install.py               # Cross-platform installer
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
