#!/usr/bin/env bash
# Launcher for the desktop entry. Desktop Entry field codes cannot expand
# $HOME (%h is not valid), so the path is resolved here instead.
#
# -n keeps a second launch from starting a second instance. That matters now
# that the shell paints a persistent call bar: duplicates would stack their
# overlays on top of each other at the same spot.
#
# Zombie guard: qs -n exits 0 with "An instance of this configuration is
# already running" even when that instance has no window (hidden, crashed
# engine, compositor unmap). The desktop entry then appears dead -- clicks do
# nothing -- while the process lingers. Window presence, not process presence,
# is the real test; a windowless instance is killed and restarted here.

CONFIG="$(dirname "$(readlink -f "$0")")/shell.qml"

window_mapped() {
  hyprctl clients -j 2>/dev/null | grep -q '"title": "Dialer"'
}

# Fast path: nothing of ours running, or a window already up.
if ! pgrep -f "qs -n -p $CONFIG" >/dev/null 2>&1; then
  exec qs -n -p "$CONFIG"
fi

if window_mapped; then
  # Already running with a window; raise it and exit.
  hyprctl dispatch focuswindow "title:Dialer" >/dev/null 2>&1
  exit 0
fi

# Process alive, window gone: a second launch would no-op on the -n lock.
# Kill the husk and start fresh.
pkill -f "qs -n -p $CONFIG" 2>/dev/null
sleep 0.3
exec qs -n -p "$CONFIG"