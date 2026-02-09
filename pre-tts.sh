#!/bin/bash

PID=$(pidof spotifyd)
CONTROL_NAME="rs.spotifyd.instance$PID"
MPRIS_NAME="org.mpris.MediaPlayer2.spotifyd.instance$PID"

# Wait for spotifyd to appear on D-Bus
for i in {1..10}; do
    dbus-send --print-reply --dest=org.freedesktop.DBus /org/freedesktop/DBus \
        org.freedesktop.DBus.ListNames | grep -q "$CONTROL_NAME" && break
    sleep 0.3
done

# Transfer playback
dbus-send --system --print-reply --dest=$CONTROL_NAME /rs/spotifyd/Controls rs.spotifyd.Controls.TransferPlayback

# Now you can safely call MPRIS methods
dbus-send --system --print-reply --dest=$MPRIS_NAME /org/mpris/MediaPlayer2 \
    org.mpris.MediaPlayer2.Player.Pause
