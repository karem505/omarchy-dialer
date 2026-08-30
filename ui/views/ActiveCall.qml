import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."
import "../components"

ColumnLayout {
    id: root
    required property var bridge
    required property var call

    property int elapsed: 0
    spacing: 16

    Timer {
        interval: 1000
        running: root.call && root.call.state === "active"
        repeat: true
        onTriggered: root.elapsed++
    }

    function clock(s) {
        const m = Math.floor(s / 60), r = s % 60;
        return m + ":" + (r < 10 ? "0" : "") + r;
    }

    Text {
        Layout.alignment: Qt.AlignHCenter
        text: root.call ? (root.call.name || root.call.line) : ""
        color: Theme.foreground
        font.pixelSize: 24
    }

    Text {
        Layout.alignment: Qt.AlignHCenter
        text: root.call && root.call.state === "active"
              ? root.clock(root.elapsed)
              : (root.call ? root.call.state : "")
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
