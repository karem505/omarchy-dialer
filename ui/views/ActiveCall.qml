import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."
import "../components"

ColumnLayout {
    id: root
    required property var bridge
    required property var call

    spacing: 16

    Text {
        Layout.alignment: Qt.AlignHCenter
        text: root.bridge.labelFor(root.call)
        color: Theme.foreground
        font.pixelSize: 24
    }

    Text {
        Layout.alignment: Qt.AlignHCenter
        // Timed from when the daemon saw the call connect, not from when
        // this view was built -- opening the window mid-call used to restart
        // the count from zero.
        text: {
            if (!root.call) return "";
            if (root.call.state !== "active") return root.call.state;
            const d = root.bridge.duration(root.call);
            return d.length > 0 ? d : "on call";
        }
        color: Theme.dim
        font.pixelSize: 16
    }

    Text {
        Layout.alignment: Qt.AlignHCenter
        // Codec 2 is mSBC; anything else is narrowband CVSD.
        text: root.bridge.codec === 2 ? "HD voice" : ""
        color: Theme.success
        font.pixelSize: 12
    }

    Keypad {
        Layout.alignment: Qt.AlignHCenter
        onDigit: (d) => root.bridge.tones(d)
    }

    // HFP volume is a 0-15 scale on the wire, not 0-100.
    GridLayout {
        Layout.fillWidth: true
        columns: 2
        columnSpacing: 8

        Text { text: "Mic"; color: Theme.dim; font.pixelSize: 12 }
        Slider {
            Layout.fillWidth: true
            from: 0; to: 15; stepSize: 1; value: 15
            onMoved: root.bridge.setVolume("mic", Math.round(value))
        }

        Text { text: "Speaker"; color: Theme.dim; font.pixelSize: 12 }
        Slider {
            Layout.fillWidth: true
            from: 0; to: 15; stepSize: 1; value: 15
            onMoved: root.bridge.setVolume("speaker", Math.round(value))
        }
    }

    Rectangle {
        Layout.fillWidth: true
        height: 44
        radius: 8
        color: Theme.danger
        Text {
            anchors.centerIn: parent
            text: "Hang up"
            color: Theme.background
            font.bold: true
        }
        MouseArea {
            anchors.fill: parent
            onClicked: root.bridge.hangup(root.call.id)
        }
    }
}
