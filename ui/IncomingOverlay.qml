import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "."

// A ringing phone has to interrupt whatever you were doing, so this is a
// layer-shell overlay rather than a window: it draws above fullscreen apps,
// follows you to whichever workspace you are on, and takes keyboard focus.
// The main Dialer window cannot do that -- toggling its `visible` does
// nothing when it is already open behind something else.
Scope {
    id: root
    required property var bridge

    readonly property var call: {
        for (let i = 0; i < bridge.calls.count; i++) {
            const c = bridge.calls.get(i);
            if (bridge.isRinging(c)) return c;
        }
        return null;
    }
    // Exclusive keyboard focus is a loaded gun: if this surface ever stayed
    // up, the keyboard would be captured with no way out. Ringing therefore
    // expires on its own, the way a real phone stops ringing, and the
    // overlay releases focus even if the daemon never tells us the call
    // ended. The call itself is left alone -- only the UI gives up.
    property bool expired: false
    property bool dismissed: false

    // The call is still ringing in all of these states -- only the size of
    // the UI changes. Dismissing must never hang up on the caller.
    readonly property bool ringing: call !== null
    readonly property bool showCard: ringing && !expired && !dismissed
    readonly property bool showPill: ringing && (expired || dismissed)

    property int ringTimeoutMs: 45000

    // Reset on the call's identity, not on the `call` object. A ringing call
    // keeps emitting property updates -- the caller's name arrives after the
    // number, for instance -- and each one hands back a fresh ListModel row
    // object. Watching that made every update undo the dismissal, so "Later"
    // had to be pressed once per update before it stuck.
    readonly property string callId: call ? call.id : ""
    onCallIdChanged: { expired = false; dismissed = false; }

    function dismiss() { root.dismissed = true; }

    // Exclusive keyboard focus is a loaded gun: if the card ever stayed up,
    // the keyboard would be captured with no way out. It therefore expires on
    // its own, the way a real phone stops ringing in your face, and falls
    // back to the pill rather than vanishing -- the call is still there.
    Timer {
        interval: root.ringTimeoutMs
        running: root.showCard
        onTriggered: root.expired = true
    }

    // Prefer the contact book over a bare number.
    readonly property string who: bridge.labelFor(call)
    readonly property string subtitle: {
        if (!call) return "";
        return (call.name || bridge.nameFor(call.line)) ? call.line : "";
    }

    function answer() { if (call) bridge.answer(call.id); }
    function reject() { if (call) bridge.hangup(call.id); }

    onShowCardChanged: if (!showCard) ringer.running = false

    // Loop the ringtone for as long as the call is offered. pw-play exits
    // after one play, so a Timer restarts it rather than relying on a flag.
    Process {
        id: ringer
        command: ["pw-play", root.ringtone]
    }
    // Settable so a different tone can be used, or silenced entirely by
    // assigning an empty string.
    property string ringtone:
        "/usr/share/sounds/freedesktop/stereo/phone-incoming-call.oga"

    Timer {
        interval: 3000
        repeat: true
        running: root.showCard && root.ringtone.length > 0
        triggeredOnStart: true
        onTriggered: if (!ringer.running) ringer.running = true
    }

    // Dismissed calls park here: a small strip at the top of the screen,
    // alongside the Omarchy bar. It takes no keyboard focus and reserves no
    // screen space, so it never gets in the way -- but the call is still
    // ringing and one click brings the card back.
    PanelWindow {
        id: pill
        visible: root.showPill
        anchors { top: true; right: true }
        margins.top: 34
        margins.right: 12
        implicitWidth: pillBody.width
        implicitHeight: 40
        color: "transparent"
        WlrLayershell.namespace: "omarchy-dialer-pill"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Ignore

        Rectangle {
            id: pillBody
            height: 36
            width: pillRow.implicitWidth + 24
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right
            radius: 18
            color: Theme.background
            border.width: 1
            border.color: Theme.success

            // Keep it visibly alive so a parked call is not forgotten.
            SequentialAnimation on border.color {
                running: root.showPill
                loops: Animation.Infinite
                ColorAnimation { to: Theme.accent;  duration: 900 }
                ColorAnimation { to: Theme.success; duration: 900 }
            }

            RowLayout {
                id: pillRow
                anchors.centerIn: parent
                spacing: 10

                Text {
                    text: "\u260E  " + root.who
                    color: Theme.foreground
                    font.pixelSize: 13
                }

                Rectangle {
                    width: 62; height: 24; radius: 12
                    color: pillAnswer.containsMouse
                           ? Qt.lighter(Theme.success, 1.15) : Theme.success
                    Text {
                        anchors.centerIn: parent
                        text: "Answer"
                        color: Theme.background
                        font.pixelSize: 11
                        font.bold: true
                    }
                    MouseArea {
                        id: pillAnswer
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: root.answer()
                    }
                }
            }

            // Anywhere else on the pill reopens the full card.
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                z: -1
                onClicked: { root.dismissed = false; root.expired = false; }
            }
        }
    }

    PanelWindow {
        visible: root.showCard
        anchors { top: true; bottom: true; left: true; right: true }
        color: "transparent"
        WlrLayershell.namespace: "omarchy-dialer-incoming"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
        exclusionMode: ExclusionMode.Ignore

        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, 0.45)
            MouseArea { anchors.fill: parent; onClicked: root.dismiss() }
        }

        Rectangle {
            id: card
            width: 420
            height: 260
            radius: 16
            anchors.centerIn: parent
            color: Theme.background
            border.width: 2
            border.color: Theme.accent
            focus: true

            Keys.onPressed: (event) => {
                if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                    root.answer(); event.accepted = true;
                } else if (event.key === Qt.Key_Escape
                           || event.key === Qt.Key_Down) {
                    // Escape hides without hanging up; rejecting is explicit.
                    root.dismiss(); event.accepted = true;
                } else if (event.key === Qt.Key_Delete
                           || event.key === Qt.Key_Backspace) {
                    root.reject(); event.accepted = true;
                }
            }

            // A soft pulse on the border, so it reads as ringing rather than
            // as a static dialog you might not notice.
            SequentialAnimation on border.color {
                running: root.showCard
                loops: Animation.Infinite
                ColorAnimation { to: Theme.success; duration: 700 }
                ColorAnimation { to: Theme.accent;  duration: 700 }
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 24
                spacing: 10

                Text {
                    Layout.alignment: Qt.AlignHCenter
                    text: "Incoming call"
                    color: Theme.dim
                    font.pixelSize: 13
                }

                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    text: root.who
                    color: Theme.foreground
                    font.pixelSize: 26
                    elide: Text.ElideRight
                }

                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    visible: root.subtitle.length > 0
                    text: root.subtitle
                    color: Theme.dim
                    font.pixelSize: 14
                }

                Item { Layout.fillHeight: true }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12

                    Rectangle {
                        Layout.preferredWidth: 110
                        height: 50
                        radius: 10
                        color: dismissHover.containsMouse
                               ? Theme.selection : Theme.surface
                        Text {
                            anchors.centerIn: parent
                            text: "Later  (Esc)"
                            color: Theme.dim
                            font.pixelSize: 13
                        }
                        MouseArea {
                            id: dismissHover
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: root.dismiss()
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        height: 50
                        radius: 10
                        color: rejectHover.containsMouse
                               ? Qt.lighter(Theme.danger, 1.15) : Theme.danger
                        Text {
                            anchors.centerIn: parent
                            text: "Reject  (Del)"
                            color: Theme.background
                            font.bold: true
                        }
                        MouseArea {
                            id: rejectHover
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: root.reject()
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        height: 50
                        radius: 10
                        color: answerHover.containsMouse
                               ? Qt.lighter(Theme.success, 1.15) : Theme.success
                        Text {
                            anchors.centerIn: parent
                            text: "Answer  (Enter)"
                            color: Theme.background
                            font.bold: true
                        }
                        MouseArea {
                            id: answerHover
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: root.answer()
                        }
                    }
                }
            }
        }
    }
}
