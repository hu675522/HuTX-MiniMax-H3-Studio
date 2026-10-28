"""Stable plugin identity; node IDs and serialized request contracts are separate."""

PLUGIN_NAME = "HuTX-MiniMax-H3-Studio"
PLUGIN_DISPLAY_NAME = "HuTX · MiniMax H3 Studio"
PLUGIN_VERSION = "0.3.2.2"
PLUGIN_VENDOR = "HuTX"
NODE_CATEGORY = "HuTX/MiniMax H3 Studio"
LOG_PREFIX = "[HuTX H3 Studio]"

# Compatibility URL, NOT an extension static-resource path. Keep old clients
# working; register these routes exactly once on the active PromptServer.
OPTIMIZER_ROUTE_PREFIX = "/goohai/minimax-h3/prompt-optimizer"
