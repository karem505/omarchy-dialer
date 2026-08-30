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

    // oFono's vocabulary, which the PipeWire Telephony API mirrors: a second
    // call arriving while one is up is reported as "waiting", not "incoming".
    // Both are still ringing and neither is something you can talk on.
    readonly property var ringingStates: ["incoming", "waiting"]
    function isRinging(call) {
        return !!call && ringingStates.indexOf(call.state) >= 0;
    }

    // The call the window should be showing. A connected call outranks a
    // ringing one, which the incoming overlay is already presenting.
    readonly property var activeCall: {
        let ringing = null;
        for (let i = 0; i < calls.count; i++) {
            const c = calls.get(i);
            if (!isRinging(c)) return c;
            if (ringing === null) ringing = c;
        }
        return ringing;
    }

    property ListModel contacts: ListModel {}
    property bool contactsAvailable: false
    property string lastImport: ""

    // One clock for the whole shell, so the window and the status bar can
    // never disagree about how long a call has been running.
    property double now: Date.now() / 1000
    Timer {
        interval: 1000
        repeat: true
        running: root.calls.count > 0
        onTriggered: root.now = Date.now() / 1000
    }

    // The daemon stamps when a call connected. A call it adopted in progress
    // has no stamp, and we show nothing rather than a made-up number.
    function duration(call) {
        if (!call || !call.started) return "";
        const s = Math.max(0, Math.floor(root.now - call.started));
        const m = Math.floor(s / 60), r = s % 60;
        return m + ":" + (r < 10 ? "0" : "") + r;
    }

    // Name from the call itself, else the contact book, else the raw number.
    function labelFor(call) {
        if (!call) return "";
        if (call.name && call.name.length > 0) return call.name;
        const resolved = nameFor(call.line);
        return resolved.length > 0 ? resolved : (call.line || "Unknown");
    }

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
                           line: ev.line || "", name: ev.name || "",
                           started: ev.started || 0};
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
