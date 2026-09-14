# Worklog — Whisper-1 (linux-voice-assistant + Spotify)

Session date: 2026-09-14
Host: `whisper-1` (Raspberry Pi, Debian 13 "trixie", aarch64, wm8960 audio HAT)
SSH: `ssh whisper-1` (pinned to 192.168.1.23 in `~/.ssh/config` on the dev machine — mDNS for `whisper-1.lan` was flaky)

## Starting state / problem

- `voice-assistant.service` (a **user-level** systemd unit) was crash-looping (restart counter in the 50s).
- A duplicate, disabled **system-level** unit of the same name also existed — confusing, not the one actually running.
- The repo at `/home/mario/linux-voice-assistant` was stuck mid `git rebase` (started ~Apr 29) with an unresolved conflict in `linux_voice_assistant/util.py` — literal `<<<<<<<`/`=======`/`>>>>>>>` markers left in the file, which is a Python `SyntaxError`. That's what was crashing the service on every start.
- The conflict was between upstream's `util.py` changes and a local hack adding Spotify control via `playerctl` (functions `run_command`/`start_spotify`/`stop_spotify`), which were **defined but never actually wired into** `satellite.py`'s `duck()`/`unduck()` — so even before it broke, Spotify ducking never worked.

## Decision: nuke and start fresh

Repo was old (66 commits behind `OHF-Voice/linux-voice-assistant` upstream) and not worth patching. Agreed to:
- Start clean from the latest upstream code.
- Build the Spotify integration as something that survives future upstream merges cleanly.

### What was done

1. Stopped/disabled both the user-level and (now-removed) system-level `voice-assistant.service`.
2. Backed up the old repo (not deleted) to `/home/mario/linux-voice-assistant.old-20260914-154259`.
3. Fresh `git clone` of the user's fork (`origin` = `https://github.com/MafioP/linux-voice-assistant`) into `/home/mario/linux-voice-assistant`.
4. Added `upstream` remote (`https://github.com/OHF-Voice/linux-voice-assistant.git`), fast-forwarded local `main` to `upstream/main` (fork had 0 unique commits ahead, so this was a clean FF — no rebase needed).
   - **Not yet pushed to `origin`** — the Pi has no stored GitHub credentials for HTTPS push. Push this from a machine with auth configured, or set up a credential helper / SSH remote on the Pi if you want `git push` to work from there directly.
5. Restored `preferences.json` from the backup (wake word models themselves — `hey_luna`, `choo_choo_homie`, etc. — turned out to already be bundled in the fresh upstream checkout, nothing custom needed restoring there).
6. Ran `./script/setup --dev`. Only Python 3.13 is available on Debian 13 trixie (no 3.11/3.12 package) — used it directly, all wheels (including the wake-word/audio native deps) installed cleanly on aarch64, no build issues.
7. Rebuilt `start.sh` and the systemd user unit — see "Audio/mixer fixes" below for why.

## Spotify integration — architecture decision

Upstream added a **Peripheral WebSocket API** (`ws://localhost:6055`, see `docs/peripheral_api.md`) specifically for external processes to react to the assistant's state (events like `wake_word_detected`, `listening`, `thinking`, `tts_speaking`, `tts_finished`, `idle`) without modifying LVA's own code.

Built the Spotify ducking as a **fully standalone peripheral script** instead of patching `satellite.py`/`util.py` directly:

- `examples/Spotify Ducking/spotify_duck.py` — connects to the peripheral WebSocket API, ducks/restores Spotify's volume on pipeline events. Own venv at `examples/Spotify Ducking/.venv` (deps: `websockets`, `pulsectl`).
- **Ducking mechanism**: adjusts the **PulseAudio sink-input volume** directly (via `pulsectl`), *not* MPRIS. Reasons:
  - `spotifyd`'s MPRIS player registers as `spotifyd.instance<PID>` (not just `spotifyd`) — the old code's hardcoded `playerctl -p spotifyd ...` never matched, which is why it never worked.
  - MPRIS `Volume` property support is unreliable/minimal in spotifyd anyway; PulseAudio per-stream volume always works regardless.
  - The spotifyd stream is identified by matching `application.process.binary == "spotifyd"` in the PulseAudio stream proplist (confirmed empirically via `pactl list sink-inputs` while Spotify Connect was active).
- Event mapping: `wake_word_detected`/`listening`/`thinking`/`tts_speaking` → duck to `--duck-factor` (default `0.3`, i.e. 30% of whatever volume the stream was at); `tts_finished`/`idle`/`pipeline_error`/`disconnected` → restore saved volume.
- Runs as systemd user service `spotify-duck.service` (`~/.config/systemd/user/spotify-duck.service`), `After=`/`Wants=` `voice-assistant.service` and `spotifyd.service`, `Restart=always`.
  - **Gotcha hit**: `ExecStart=` in a systemd unit splits on unescaped spaces — the path `.../examples/Spotify Ducking/.venv/bin/python3` has a space in it (matches upstream's own `examples/` naming convention, e.g. "ReSpeaker 2mic HAT"). Fixed by quoting the executable in `ExecStart=`.
- Verified end-to-end live: triggering the wake word audibly ducked Spotify and restored it after the response finished.

This whole integration lives outside `linux_voice_assistant/` and outside any upstream file — future `git merge upstream/main` should never conflict with it.

## Audio / mixer fixes

Two separate but related complaints: assistant volume was way too loud, and the mixer volume reset to ~0 on every reboot.

Root causes found:
1. Old `start.sh` ran `amixer -c 1 set Headphones 100%` — **wrong control name**. The real wm8960 card control is `Headphone` (singular). This command silently did nothing, ever.
2. `alsa-restore.service` (the systemd mechanism that's supposed to restore mixer levels at boot) **fails for this card**: `failed to import hw:1 use case configuration -2` (no UCM profile for the wm8960 driver). So nothing restores the hardware mixer state at boot at all — it sits at the kernel driver's power-on default (~0), which is exactly the "resets on reboot" symptom.
3. Combined with LVA's own software volume defaulting to `1.0` (no `volume` key in `preferences.json`) and the hardware gain having drifted up from manual tinkering over the Pi's 4-month uptime, you'd get two gain stages both near max simultaneously, whenever the hw gain happened to be high, giving very loud output.

Fix (in `start.sh`, runs on every boot after a 10s settle delay):
```sh
amixer -c 1 set Speaker 90% unmute
amixer -c 1 set Headphone 90% unmute
```
- `90%` here is `amixer`'s **raw linear percentage of the register's 0-127 range**, which worked out to **-7dB**. Note this is *not* the same percentage `alsamixer`'s TUI displays for the same control — alsamixer uses a separate ALSA "mapped/perceptual" volume curve for display, so the same -7dB register value shows as ~61% there. Both are correct; they're just different display conventions for the same underlying value. Don't try to make the numbers match across tools — tune by ear (raise/lower the `amixer` percentage) instead.
- Software volume (`preferences.json` -> `"volume": 1.0`) is kept at 100%. Rationale: hardware analog gain should be the primary/coarse loudness control (headroom), software/digital volume should stay near unity to avoid losing dynamic range — the HA Media Player volume slider is the day-to-day fine control on top of that.
- Verified after an actual reboot: hardware gain held at the configured level (no more reset to 0), and both `voice-assistant.service` and `spotify-duck.service` auto-started cleanly (user lingering was already enabled for `mario`, confirmed via `loginctl show-user mario -p Linger` -> `yes`).

## Current running state

- `voice-assistant.service` (user unit) — LVA itself, `start.sh` -> `script/run --name 'Whisper-1' --debug --audio-output-device 'pulse/alsa_output.hw_wm8960soundcard_0'`.
- `spotify-duck.service` (user unit) — the Spotify ducking peripheral script.
- `spotifyd.service` (user unit, pre-existing, untouched) — Spotify Connect receiver, device name "Whisper-1".
- Single systemd unit for LVA now (the stray disabled system-level duplicate was deleted).

## Known follow-ups / not yet done

- `origin` (the user's fork) is **not yet pushed** with the upstream fast-forward — needs GitHub auth set up on the Pi, or push from another machine.
- Old broken repo backup still sits at `/home/mario/linux-voice-assistant.old-20260914-154259` — safe to delete once you're confident the fresh setup is solid.
- `spotify_duck.py`'s `--duck-factor` (default `0.3`) hasn't been tuned/discussed beyond "it works" — adjust via the systemd unit's `ExecStart` args if 30% feels wrong.
- No dedicated error handling yet for spotifyd being unavailable/not-yet-registered on the PulseAudio bus at the moment `duck()` fires (it just no-ops if no matching stream is found — hasn't caused a problem in testing, but hasn't been stress-tested either).
