import QtQuick
import QtQuick.Layouts
import Quickshell
import "."
import "views"

ShellRoot {
    Bridge {
        id: dialer
        onConnectedChanged: if (connected) refreshContacts()
    }

    IncomingOverlay { bridge: dialer }
    ActiveCallBar   { bridge: dialer }

    FloatingWindow {
        id: win
        title: "Dialer"
        implicitWidth: 380
        implicitHeight: 620
        color: Theme.background
        visible: true

        // Single keyboard entry point for the whole window. Routing lives
        // here rather than in each view so focus never has to move between
        // them -- the Loader swapping views would otherwise drop it.
        Item {
            id: keys
            anchors.fill: parent
            focus: true

            readonly property var view: loader.item

            Keys.onPressed: (event) => {
                const c = dialer.activeCall;
                const digits = "0123456789*#+";

                // Digits reach the network as DTMF while a call is up. The
                // length check is load-bearing: modifier keys arrive with an
                // empty text, and "...".indexOf("") is 0, which would send a
                // tone command with no digits in it on every Shift press.
                if (c && !dialer.isRinging(c)
                    && event.text.length === 1 && digits.indexOf(event.text) >= 0) {
                    dialer.tones(event.text);
                    event.accepted = true;
                    return;
                }

                // Incoming calls are handled by the overlay, which holds
                // exclusive keyboard focus while it is up.
                if (dialer.isRinging(c)) return;

                if (c) {
                    if (event.key === Qt.Key_Escape) {
                        dialer.hangup(c.id); event.accepted = true;
                    }
                    return;
                }

                // Idle: digits build the number, letters search contacts.
                if (!keys.view) return;
                if (digits.indexOf(event.text) >= 0 && event.text.length === 1) {
                    keys.view.digit(event.text); event.accepted = true;
                } else if (event.key === Qt.Key_Backspace) {
                    keys.view.backspace(); event.accepted = true;
                } else if (event.key === Qt.Key_Escape) {
                    keys.view.clear(); event.accepted = true;
                } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                    keys.view.call(); event.accepted = true;
                } else if (event.text.length === 1 && event.text >= " ") {
                    // Any printable character searches -- Arabic, accented
                    // Latin, anything. Digits and DTMF symbols were handled
                    // above, so whatever reaches here is a search character.
                    keys.view.letter(event.text); event.accepted = true;
                }
            }
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: "Dialer"
                    color: Theme.foreground
                    font.pixelSize: 18
                    font.bold: true
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: dialer.connected ? dialer.gatewayName : "No phone connected"
                    color: dialer.connected ? Theme.dim : Theme.danger
                    font.pixelSize: 12
                }
            }

            Loader {
                id: loader
                Layout.fillWidth: true
                Layout.fillHeight: true
                sourceComponent: {
                    const c = dialer.activeCall;
                    // An incoming call is presented by IncomingOverlay, so the
                    // window keeps showing the dialer underneath it.
                    if (!c || dialer.isRinging(c)) return idleView;
                    return activeView;
                }
            }

            Component { id: idleView;     Idle       { bridge: dialer } }
            Component { id: activeView;   ActiveCall { bridge: dialer; call: dialer.activeCall } }
        }
    }
}
