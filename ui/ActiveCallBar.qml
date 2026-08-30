import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import "."
import "components"

// A live call has to be reachable from wherever you happen to be looking.
// The Dialer window is an ordinary floating window: answering a call from the
// incoming overlay leaves it buried behind whatever you were working in, or
// on another workspace entirely, so the call effectively vanishes.
//
// This strip is a layer-shell surface instead. It sits under the Omarchy bar
// on every workspace, for as long as a call is up, and carries enough
// controls -- mute, keypad, hang up -- that the window never has to be found.
Scope {
    id: root
    required property var bridge

    // The first call that is not merely ringing. Incoming calls belong to
    // IncomingOverlay; this strip owns everything after you answer.
    readonly property var call: {
        for (let i = 0; i < bridge.calls.count; i++) {
            const c = bridge.calls.get(i);
            if (!bridge.isRinging(c)) return c;
        }
        return null;
    }
    readonly property bool live: call !== null
    readonly property string callId: call ? call.id : ""

    property bool padOpen: false
    property bool muted: false

    // Each new call starts collapsed and unmuted -- a mute carried over from
    // a previous call would silence you with no visible cause.
    onCallIdChanged: {
        padOpen = false;
        if (muted) setMuted(false);
    }

    function setMuted(on) {
        root.muted = on;
        // HFP microphone gain is a 0-15 scale on the wire, not 0-100.
        bridge.setVolume("mic", on ? 0 : 15);
    }

    function hangup() { if (call) bridge.hangup(call.id); }

    readonly property string who: bridge.labelFor(call)
    readonly property string status: {
        if (!call) return "";
        if (call.state !== "active") return call.state;
        const d = bridge.duration(call);
        // A call adopted in progress has no known start time, and "on call"
        // is honest where a duration counted from now would not be.
        return d.length > 0 ? d : "on call";
    }

    PanelWindow {
        visible: root.live
        // Anchoring the top edge alone leaves the surface centred and only as
        // wide as its content, so the rest of the strip stays clickable.
        anchors.top: true
        margins.top: 34
        implicitWidth: content.implicitWidth + 28
        implicitHeight: content.implicitHeight + 20
        color: "transparent"
        WlrLayershell.namespace: "omarchy-dialer-callbar"
        WlrLayershell.layer: WlrLayer.Overlay
        // Only grab the keyboard once the keypad is open, and only on click:
        // a bar that held focus for the whole call would break typing
        // everywhere else while you talk.
        WlrLayershell.keyboardFocus: root.padOpen
                                     ? WlrKeyboardFocus.OnDemand
                                     : WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Ignore

        Rectangle {
            anchors.fill: parent
            radius: 14
            color: Theme.background
            border.width: 1
            border.color: root.call && root.call.state === "active"
                          ? Theme.success : Theme.accent

            focus: true
            Keys.onPressed: (event) => {
                if (event.key === Qt.Key_Escape) {
                    root.padOpen = false; event.accepted = true;
                } else if (event.text.length === 1
                           && "0123456789*#".indexOf(event.text) >= 0) {
                    root.bridge.tones(event.text); event.accepted = true;
                }
            }

            ColumnLayout {
                id: content
                anchors.centerIn: parent
                spacing: 12

                RowLayout {
                    Layout.alignment: Qt.AlignHCenter
                    spacing: 12

                    // Breathes while connected, so a call left running in the
                    // background stays noticeable.
                    Rectangle {
                        implicitWidth: 9; implicitHeight: 9; radius: 5
                        color: Theme.success
                        SequentialAnimation on opacity {
                            running: root.live
                            loops: Animation.Infinite
                            NumberAnimation { to: 0.25; duration: 900 }
                            NumberAnimation { to: 1.0;  duration: 900 }
                        }
                    }

                    Text {
                        Layout.maximumWidth: 220
                        text: root.who
                        color: Theme.foreground
                        font.pixelSize: 13
                        elide: Text.ElideRight
                    }

                    Text {
                        text: root.status
                        color: Theme.dim
                        font.pixelSize: 13
                        // Fixed-width digits stop the row jittering every second.
                        font.family: "monospace"
                    }

                    Text {
                        // Codec 2 is mSBC; anything else is narrowband CVSD.
                        visible: root.bridge.codec === 2
                        text: "HD"
                        color: Theme.success
                        font.pixelSize: 10
                        font.bold: true
                    }

                    BarButton {
                        label: root.muted ? "Unmute" : "Mute"
                        tint: root.muted ? Theme.accent : Theme.surface
                        textColor: root.muted ? Theme.background : Theme.foreground
                        onClicked: root.setMuted(!root.muted)
                    }

                    BarButton {
                        label: "Keypad"
                        tint: root.padOpen ? Theme.selection : Theme.surface
                        onClicked: root.padOpen = !root.padOpen
                    }

                    BarButton {
                        label: "Hang up"
                        tint: Theme.danger
                        textColor: Theme.background
                        bold: true
                        onClicked: root.hangup()
                    }
                }

                Keypad {
                    Layout.alignment: Qt.AlignHCenter
                    // Layouts skip invisible items, so the strip shrinks back
                    // to one row on its own when the keypad closes.
                    visible: root.padOpen
                    onDigit: (d) => root.bridge.tones(d)
                }
            }
        }
    }

    // Small pill button, kept inline so the strip stays self-contained.
    component BarButton: Rectangle {
        id: btn
        property string label: ""
        property color tint: Theme.surface
        property color textColor: Theme.foreground
        property bool bold: false
        signal clicked

        implicitWidth: caption.implicitWidth + 20
        implicitHeight: 26
        radius: 13
        color: hover.containsMouse ? Qt.lighter(btn.tint, 1.2) : btn.tint

        Text {
            id: caption
            anchors.centerIn: parent
            text: btn.label
            color: btn.textColor
            font.pixelSize: 11
            font.bold: btn.bold
        }

        MouseArea {
            id: hover
            anchors.fill: parent
            hoverEnabled: true
            onClicked: btn.clicked()
        }
    }
}
