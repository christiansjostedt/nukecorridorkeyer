"""
CorridorKeyer for Nuke — menu.py
Loaded at Nuke startup (GUI mode). Adds toolbar entries.
"""

import os
import nuke

plugin_dir = os.path.dirname(__file__)
icon_path = os.path.join(plugin_dir, "icons", "corridor_keyer.png")
icon = icon_path if os.path.exists(icon_path) else ""


def create_corridor_keyer():
    """Create a CorridorKeyer node in the DAG."""
    node = nuke.createNode("CorridorKeyer")
    # Set default frame range from script
    from corridor_keyer import node as ck_node
    ck_node.on_create(node)
    return node


# Add to Nodes toolbar
toolbar = nuke.toolbar("Nodes")
keyer_menu = toolbar.addMenu("CorridorKeyer", icon=icon)
keyer_menu.addCommand(
    "CorridorKeyer",
    "create_corridor_keyer()",
    icon=icon,
)

# Also add under the standard Keyer menu for discoverability
keyer_toolbar = toolbar.findItem("Keyer")
if keyer_toolbar:
    keyer_toolbar.addCommand(
        "CorridorKeyer",
        "create_corridor_keyer()",
        icon=icon,
    )
