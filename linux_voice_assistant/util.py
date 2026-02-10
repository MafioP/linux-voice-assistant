"""Utility methods."""

import re
import subprocess
import uuid
import logging
from collections.abc import Callable
from typing import Optional

_LOGGER = logging.getLogger(__name__)


def get_mac() -> str:
    mac = uuid.getnode()
    mac_str = ":".join(f"{(mac >> i) & 0xff:02x}" for i in range(40, -1, -8))
    return mac_str


def call_all(*callables: Optional[Callable[[], None]]) -> None:
    for item in filter(None, callables):
        item()


def run_command(command: Optional[str]) -> None:
    if not command:
        return

    _LOGGER.debug("Running %s", command)

    result = subprocess.run(command, shell=True, capture_output=True)
    _LOGGER.debug("Output: %s", result.stdout.strip())
    
def start_spotify() -> None:
    run_command("playerctl play-pause")
    run_command("playerctl -l")
    return

def stop_spotify() -> None:
    run_command("playerctl pause")
    run_command("playerctl -l")
    return

def get_spotify_status() -> str:
    result = subprocess.run(
        ["playerctl", "status"],
        capture_output=True,
        text=True
    )

    return result.stdout.strip()