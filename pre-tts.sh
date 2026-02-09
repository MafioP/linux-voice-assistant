#!/bin/bash

PID=$(pidof spotifyd) || exit 0
MPRIS="org.mpris.MediaPlayer2.spotifyd.instance$PID"

dbus-send --system \
  --dest="$MPRIS" \
  /org/mpris/MediaPlayer2 \
  org.mpris.MediaPlayer2.Player.Pause \
  >/dev/null 2>&1 &

exit 0