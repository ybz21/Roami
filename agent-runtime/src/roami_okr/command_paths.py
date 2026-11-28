"""Public command paths registered by the project integration."""

import json
from pathlib import Path

from roami_agent.tools.command_families import COMMANDS

PROJECT_COMMAND_PATHS = {
    **COMMANDS,
    **json.loads(Path(__file__).with_name("commands.json").read_text()),
}
