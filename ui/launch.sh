#!/usr/bin/env bash
# Launcher for the desktop entry. Desktop Entry field codes cannot expand
# $HOME (%h is not valid), so the path is resolved here instead.
#
# -n keeps a second launch from starting a second instance. That matters now
# that the shell paints a persistent call bar: duplicates would stack their
# overlays on top of each other at the same spot.
exec qs -n -p "$(dirname "$(readlink -f "$0")")/shell.qml"
