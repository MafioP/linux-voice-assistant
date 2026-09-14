#!/usr/bin/env python3
"""Ducks Spotify (spotifyd) audio while the linux-voice-assistant pipeline is active.

Connects to LVA's peripheral WebSocket API (docs/peripheral_api.md) and reacts
to voice-pipeline events by lowering spotifyd's PulseAudio stream volume, then
restoring it once the assistant goes back to idle. Runs entirely outside of
LVA's own code, so it never conflicts with upstream LVA updates.
"""

import argparse
import asyncio
import logging
import signal
from json import dumps, loads
from typing import Dict, Iterable, List

import pulsectl
import websockets

_LOGGER = logging.getLogger("spotify_duck")

DUCK_EVENTS = {"wake_word_detected", "listening", "thinking", "tts_speaking"}
UNDUCK_EVENTS = {"tts_finished", "idle", "pipeline_error", "disconnected"}

# Property values PulseAudio streams from spotifyd/librespot commonly set.
_STREAM_NAME_HINTS = ("spotify", "librespot")
_PROPLIST_KEYS = ("application.name", "application.process.binary", "media.name")


def _matches_spotify(proplist: Dict[str, str]) -> bool:
    for key in _PROPLIST_KEYS:
        value = proplist.get(key, "")
        if value and any(hint in value.lower() for hint in _STREAM_NAME_HINTS):
            return True
    return False


class SpotifyDucker:
    """Ducks/restores the volume of spotifyd's PulseAudio stream(s)."""

    def __init__(self, duck_factor: float) -> None:
        self._duck_factor = duck_factor
        self._ducked = False
        self._saved_volumes: Dict[int, pulsectl.PulseVolumeInfo] = {}

    @staticmethod
    def _find_spotify_inputs(pulse: "pulsectl.Pulse") -> List["pulsectl.PulseSinkInputInfo"]:
        return [i for i in pulse.sink_input_list() if _matches_spotify(i.proplist)]

    def duck(self) -> None:
        if self._ducked:
            return

        with pulsectl.Pulse("lva-spotify-duck-write") as pulse:
            streams = self._find_spotify_inputs(pulse)
            if not streams:
                _LOGGER.debug("duck(): no active Spotify stream found, nothing to do")
                return

            for stream in streams:
                self._saved_volumes[stream.index] = stream.volume
                ducked = pulsectl.PulseVolumeInfo(
                    [v * self._duck_factor for v in stream.volume.values]
                )
                pulse.volume_set(stream, ducked)

            self._ducked = True
            _LOGGER.info("Ducked Spotify volume (%d stream(s))", len(streams))

    def unduck(self) -> None:
        if not self._ducked:
            return

        with pulsectl.Pulse("lva-spotify-duck-write") as pulse:
            current = {i.index: i for i in self._find_spotify_inputs(pulse)}
            restored = 0
            for index, saved_volume in self._saved_volumes.items():
                stream = current.get(index)
                if stream is None:
                    continue
                pulse.volume_set(stream, saved_volume)
                restored += 1

            _LOGGER.info("Restored Spotify volume (%d stream(s))", restored)

        self._saved_volumes.clear()
        self._ducked = False


async def _run(uri: str, ducker: SpotifyDucker) -> None:
    backoff = 1.0
    while True:
        try:
            async with websockets.connect(uri) as ws:
                _LOGGER.info("Connected to LVA peripheral API at %s", uri)
                backoff = 1.0
                async for raw in ws:
                    msg = loads(raw)
                    event = msg.get("event")
                    if event in DUCK_EVENTS:
                        ducker.duck()
                    elif event in UNDUCK_EVENTS:
                        ducker.unduck()
        except (ConnectionRefusedError, OSError, websockets.exceptions.WebSocketException) as err:
            ducker.unduck()
            _LOGGER.warning("Disconnected from LVA (%s); retrying in %.0fs", err, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


async def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", default="ws://localhost:6055", help="LVA peripheral WebSocket URI")
    parser.add_argument("--duck-factor", type=float, default=0.3, help="Volume multiplier while ducked (0.0-1.0)")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    ducker = SpotifyDucker(args.duck_factor)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _on_signal() -> None:
        ducker.unduck()
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _on_signal)

    run_task = asyncio.create_task(_run(args.uri, ducker))
    await stop_event.wait()
    run_task.cancel()


if __name__ == "__main__":
    asyncio.run(_main())
