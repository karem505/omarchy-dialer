pragma Singleton

import Quickshell
import Quickshell.Io

Singleton {
    id: root

    // Omarchy repoints ~/.local/state/omarchy/current on theme change.
    readonly property string themeFile: Quickshell.env("HOME")
        + "/.local/state/omarchy/current/theme/colors.toml"

    property string background: "#060B1E"
    property string surface:    "#131a3a"
    property string foreground: "#ffcead"
    property string dim:        "#6d7db6"
    property string accent:     "#7d82d9"
    property string selection:  "#252e56"
    property string danger:     "#ED5B5A"
    property string success:    "#92a593"
    property bool   isDark:     true

    // colors.toml is flat `key = "value"` lines; a full TOML parser is overkill.
    function parse(text) {
        const out = {};
        for (const line of text.split("\n")) {
            const m = line.match(/^\s*([a-z_]+)\s*=\s*"([^"]*)"/);
            if (m) out[m[1]] = m[2];
        }
        return out;
    }

    function apply(text) {
        const c = parse(text);
        if (c.background)         root.background = c.background;
        if (c.lighter_background) root.surface    = c.lighter_background;
        if (c.foreground)         root.foreground = c.foreground;
        if (c.dark_foreground)    root.dim        = c.dark_foreground;
        if (c.accent)             root.accent     = c.accent;
        if (c.selection)          root.selection  = c.selection;
        if (c.red)                root.danger     = c.red;
        if (c.green)              root.success    = c.green;
        root.isDark = (c.mode || "dark") === "dark";
    }

    FileView {
        id: file
        path: root.themeFile
        watchChanges: true
        onLoaded: root.apply(file.text())
        onFileChanged: file.reload()
    }
}
