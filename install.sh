#!/usr/bin/env bash
set -euo pipefail

PREFIX="${HOME}/.local/share/omarchy-dialer"
WP_CONF="${HOME}/.config/wireplumber/wireplumber.conf.d/bluetooth-a2dp-autoconnect.conf"

echo "==> Installing to ${PREFIX}"
mkdir -p "${PREFIX}"
# Replace rather than merge: a plain copy leaves files behind that a later
# version deleted, and stale .qml in ui/ is confusing at best.
rm -rf "${PREFIX}/src" "${PREFIX}/ui"
cp -r src ui "${PREFIX}/"

echo "==> Installing desktop entry"
mkdir -p "${HOME}/.local/share/applications"
# @PREFIX@ is substituted here because Desktop Entry has no field code that
# expands $HOME -- %h is not valid and desktop-file-validate rejects it.
sed "s|@PREFIX@|${PREFIX}|g" desktop/omarchy-dialer.desktop \
  > "${HOME}/.local/share/applications/omarchy-dialer.desktop"
chmod +x "${PREFIX}/ui/launch.sh"
update-desktop-database "${HOME}/.local/share/applications" 2>/dev/null || true

echo "==> Installing icon"
# Ship our own icon: the freedesktop name "call-start" only exists in a few
# legacy themes, so most desktops render no icon at all for it.
ICONDIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
mkdir -p "${ICONDIR}"
cp desktop/icons/omarchy-dialer.svg "${ICONDIR}/"
gtk-update-icon-cache -f -t "${HOME}/.local/share/icons/hicolor" 2>/dev/null || true

echo "==> Installing user service"
mkdir -p "${HOME}/.config/systemd/user"
cp systemd/omarchy-dialerd.service "${HOME}/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now omarchy-dialerd.service

echo "==> Ensuring hfp_hf auto-connects"
if [[ -f "${WP_CONF}" ]]; then
  if grep -q "hfp_hf" "${WP_CONF}"; then
    echo "    already present, skipping"
  else
    cp "${WP_CONF}" "${WP_CONF}.bak"
    sed -i 's/bluez5\.auto-connect = \[ a2dp_sink a2dp_source \]/bluez5.auto-connect = [ hfp_hf a2dp_sink a2dp_source ]/' "${WP_CONF}"
    echo "    patched (backup at ${WP_CONF}.bak) - restarting wireplumber"
    systemctl --user restart wireplumber
  fi
else
  echo "    ${WP_CONF} not found; add hfp_hf to bluez5.auto-connect manually"
fi

cat <<'NOTE'

==> Optional: float the window
    Hyprland tiles the Dialer by default. To float it at 380x620, add this
    to ~/.config/hypr/looknfeel.lua:

        o.window({ class = "org.quickshell", title = "^Dialer$" },
                 { float = true, size = "380 620" })

    This installer does not edit your Hyprland config for you.

==> Done. Launch 'Dialer' from your app grid.
NOTE
