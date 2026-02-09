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

# Transfer playback back to spotifyd (in case another client took over)
dbus-send --system --print-reply --dest=$CONTROL_NAME /rs/spotifyd/Controls rs.spotifyd.Controls.TransferPlayback

# Resume playback
dbus-send --system --print-reply --dest=$MPRIS_NAME /org/mpris/MediaPlayer2 \
    org.mpris.MediaPlayer2.Player.Play

