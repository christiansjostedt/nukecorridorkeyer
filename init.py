"""
CorridorKeyer for Nuke — init.py
Loaded at Nuke startup. Registers plugin paths.
"""

import os
import nuke

plugin_dir = os.path.dirname(__file__)

# Add Python modules to Nuke's Python path
nuke.pluginAddPath(os.path.join(plugin_dir))

# Register gizmo directory so Nuke can find CorridorKeyer.gizmo
nuke.pluginAddPath(os.path.join(plugin_dir, "gizmos"))
