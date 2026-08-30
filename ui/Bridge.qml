import QtQuick
import Quickshell
import Quickshell.Io

Item {
    id: root

    readonly property string sockPath: (Quickshell.env("XDG_RUNTIME_DIR")
        || "/run/user/1000") + "/omarchy-dialer.sock"

    property bool   connected: false
    property string gatewayName: ""
    property string transportState: "idle"
    property int    codec: 0
    property ListModel calls: ListModel {}
    readonly property var activeCall: calls.count > 0 ? calls.get(0) : null

    property ListModel contacts: ListModel {}
    property bool contactsAvailable: false
    property string lastImport: ""

    function send(obj) { sock.write(JSON.stringify(obj) + "\n"); }

    function dial(number)            { send({cmd: "dial",   number: number}); }
    function answer(id)              { send({cmd: "answer", call: id}); }
    function hangup(id)              { send({cmd: "hangup", call: id}); }
    function tones(digits)           { send({cmd: "tones",  digits: digits}); }
    function setVolume(which, value) { send({cmd: "set_volume", which: which, value: value}); }
    function importContacts(path)    { send({cmd: "import_contacts", path: path}); }
    function refreshContacts()       { send({cmd: "contacts"}); }

    // Name for a dialled number, so the call card can show it too.
    function nameFor(number) {
        const digits = (number || "").replace(/\D/g, "").slice(-9);
        if (!digits) return "";
        for (let i = 0; i < contacts.count; i++) {
            const c = contacts.get(i);
            if (c.number.replace(/\D/g, "").slice(-9) === digits) return c.name;
        }
        return "";
    }

    function indexOfCall(id) {
        for (let i = 0; i < calls.count; i++)
            if (calls.get(i).id === id) return i;
        return -1;
    }

    function handle(ev) {
        switch (ev.ev) {
        case "gateway":
            root.connected = ev.connected;
            root.gatewayName = ev.name || ev.address || "";
            if (!ev.connected) calls.clear();
            break;
        case "transport":
            root.transportState = ev.state;
            root.codec = ev.codec || 0;
            break;
        case "call": {
            const entry = {id: ev.id, state: ev.state || "",
                           line: ev.line || "", name: ev.name || ""};
            const i = indexOfCall(ev.id);
            if (i >= 0) calls.set(i, entry); else calls.append(entry);
            break;
        }
        case "call_removed": {
            const i = indexOfCall(ev.id);
            if (i >= 0) calls.remove(i);
            break;
        }
        case "contacts": {
            root.contactsAvailable = ev.available || false;
            contacts.clear();
            for (const c of (ev.items || [])) contacts.append(c);
            break;
        }
        case "imported":
            root.lastImport = ev.added + " added, " + ev.updated + " updated"
                            + (ev.skipped ? ", " + ev.skipped + " skipped" : "");
            break;
        case "error":
            root.lastImport = "Import failed: " + ev.message;
            console.warn("dialerd error:", ev.message);
            break;
        }
    }

    Socket {
        id: sock
        path: root.sockPath
        connected: true
        onConnectionStateChanged: {
            if (!sock.connected) {
                root.connected = false;
                root.calls.clear();
                retry.start();
            }
        }
        parser: SplitParser {
            onRead: (line) => {
                try { root.handle(JSON.parse(line)); }
                catch (e) { console.warn("bad line from daemon:", line); }
            }
        }
    }

    Timer {
        id: retry
        interval: 1000
        repeat: false
        onTriggered: sock.connected = true
    }
}
