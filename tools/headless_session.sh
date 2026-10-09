#!/bin/bash
# Run a command inside a private, invisible GNOME session, so screen-recording code can be tested without touching
# the real desktop, the real audio devices or the real settings.
#
#   tools/headless_session.sh python3 -I tests/test_record_session.py
#
# What is isolated:
#   - its own D-Bus session bus and its own XDG_RUNTIME_DIR (so a separate Wayland socket, PipeWire and PulseAudio)
#   - gnome-shell --headless with one 1280x720 virtual monitor (no GPU/DRM, nothing appears on a real screen)
#   - PipeWire + WirePlumber with all hardware disabled (no real microphone or speakers are opened); null sinks stand in for
#     the speakers and the microphone
#   - GSETTINGS_BACKEND=memory, so no real dconf setting can be read or written
# The command sees: SNIPSHOT_HEADLESS=1, VIRTUAL_SINK (default output), VIRTUAL_MIC_FEED (a sink whose '.monitor'
# is a stand-in microphone you can play tones into), VIRTUAL_DEFAULT_MIC (silent default input).
set -u
# Hide the real GPUs from everything started here (bubblewrap masks /dev/dri), so the private compositor renders in
# software and cannot take video memory or anything else from the real desktop's GPU.
if [ -z "${SNIPSHOT_HL_NOGPU:-}" ]; then
    command -v bwrap >/dev/null || { echo "bubblewrap (bwrap) is required to keep the real GPU out of the test session" >&2; exit 96; }
    export SNIPSHOT_HL_NOGPU=1
    exec bwrap --dev-bind / / --tmpfs /dev/dri --die-with-parent "$0" "$@"
fi
if [ -z "${SNIPSHOT_HL_INNER:-}" ]; then
    # keep this path short: unix socket paths are limited to 108 bytes
    ROOT=$(mktemp -d /tmp/snipshot-hl.XXXXXX)
    mkdir -p "$ROOT/run" "$ROOT/config/wireplumber/wireplumber.conf.d" "$ROOT/cache" "$ROOT/data" "$ROOT/state"
    chmod 700 "$ROOT/run"
    cat > "$ROOT/config/wireplumber/wireplumber.conf.d/90-headless.conf" <<'EOF'
wireplumber.profiles = {
  main = {
    hardware.audio = disabled
    hardware.bluetooth = disabled
    hardware.video-capture = disabled
  }
}
EOF
    export XDG_RUNTIME_DIR="$ROOT/run" XDG_CONFIG_HOME="$ROOT/config" XDG_CACHE_HOME="$ROOT/cache"
    export XDG_DATA_HOME="$ROOT/data" XDG_STATE_HOME="$ROOT/state"
    export GSETTINGS_BACKEND=memory SNIPSHOT_HL_INNER=1 SNIPSHOT_HL_ROOT="$ROOT" SNIPSHOT_HEADLESS=1
    unset WAYLAND_DISPLAY DISPLAY DBUS_SESSION_BUS_ADDRESS XDG_SESSION_ID PULSE_SERVER PIPEWIRE_REMOTE
    unset GNOME_SETUP_DISPLAY GDK_BACKEND
    # not exec: after the bus and the daemons it started are gone, unmount their FUSE mounts and delete the folder
    dbus-run-session -- "$0" "$@"
    rc=$?
    sleep 1
    for m in "$ROOT/run/doc" "$ROOT/run/gvfs"; do fusermount3 -uz "$m" 2>/dev/null; done
    rm -rf "$ROOT"
    exit $rc
fi

ROOT="$SNIPSHOT_HL_ROOT"
PIDS=()
cleanup() {
    for ((i=${#PIDS[@]}-1; i>=0; i--)); do kill "${PIDS[$i]}" 2>/dev/null; done
    sleep 0.5
    for p in "${PIDS[@]}"; do kill -9 "$p" 2>/dev/null; done
}
trap cleanup EXIT

start() { "$@" >"$ROOT/$1.log" 2>&1 & PIDS+=($!); }

start pipewire
for i in $(seq 50); do [ -S "$XDG_RUNTIME_DIR/pipewire-0" ] && break; sleep 0.1; done
start wireplumber
start pipewire-pulse
for i in $(seq 50); do [ -S "$XDG_RUNTIME_DIR/pulse/native" ] && break; sleep 0.1; done

start gnome-shell --headless --wayland --no-x11 --virtual-monitor 1280x720
ok=
for i in $(seq 100); do
    if gdbus call --session --dest org.gnome.Mutter.ScreenCast --object-path /org/gnome/Mutter/ScreenCast \
        --method org.freedesktop.DBus.Peer.Ping >/dev/null 2>&1; then ok=1; break; fi
    sleep 0.2
done
if [ -z "$ok" ]; then
    echo "headless GNOME did not come up; log:" >&2; tail -20 "$ROOT/gnome-shell.log" >&2; exit 97
fi

start python3 -I "$(dirname "$(readlink -f "$0")")/fake_watcher.py"        # a tray host, like the AppIndicator extension
# GTK programs started by the command draw on the private compositor (software rendering, nothing reaches a real screen)
export WAYLAND_DISPLAY=$(ls "$XDG_RUNTIME_DIR" | grep -E '^wayland-[0-9]+$' | head -1) GDK_BACKEND=wayland GSK_RENDERER=cairo

# virtual audio that exists only inside this private PipeWire: a sink standing in for the speakers ("system sound"),
# a sink whose monitor is a controllable stand-in microphone, and a silent default microphone
export VIRTUAL_SINK=snipshot_test_sink VIRTUAL_MIC_FEED=snipshot_mic_feed VIRTUAL_DEFAULT_MIC=snipshot_default_mic
mknode() {  # name class
    pw-cli create-node adapter "{ factory.name=support.null-audio-sink node.name=$1 node.description=$1 media.class=$2 \
        object.linger=true audio.position=[FL FR] }" >/dev/null 2>&1
}
mknode $VIRTUAL_SINK Audio/Sink
mknode $VIRTUAL_MIC_FEED Audio/Sink
mknode $VIRTUAL_DEFAULT_MIC Audio/Source/Virtual
sleep 1
node_id() { pw-dump 2>/dev/null | python3 -c "
import json,sys
for o in json.load(sys.stdin):
    p=(o.get('info') or {}).get('props') or {}
    if p.get('node.name')==sys.argv[1]: print(o['id']); break" "$1"; }
wpctl set-default "$(node_id $VIRTUAL_SINK)" >/dev/null 2>&1
wpctl set-default "$(node_id $VIRTUAL_DEFAULT_MIC)" >/dev/null 2>&1

"$@"
exit $?
