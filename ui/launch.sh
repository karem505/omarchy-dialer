#!/usr/bin/env bash
# Launcher for the desktop entry. Desktop Entry field codes cannot expand
# $HOME (%h is not valid), so the path is resolved here instead.
exec qs -p "$(dirname "$(readlink -f "$0")")/shell.qml"
