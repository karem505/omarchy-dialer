import QtQuick
import QtQuick.Layouts
import ".."
import "../components"

ColumnLayout {
    id: root
    required property var bridge
    property string number: ""

    // Typing digits dials; typing letters searches the phone book.
    property string search: ""

    spacing: 10

    function digit(d) { root.number += d; }
    function backspace() {
        if (root.search.length > 0) root.search = root.search.slice(0, -1);
        else root.number = root.number.slice(0, -1);
    }
    function clear() { root.number = ""; root.search = ""; }
    function call() {
        if (root.number.length > 0 && root.bridge.connected)
            root.bridge.dial(root.number);
    }
    function letter(ch) { root.search += ch; }

    Rectangle {
        Layout.fillWidth: true
        height: 46
        radius: 8
        color: Theme.surface
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            Text {
                Layout.fillWidth: true
                elide: Text.ElideLeft
                text: root.number || "Enter a number"
                color: root.number ? Theme.foreground : Theme.dim
                font.pixelSize: 20
            }
            Text {
                visible: root.number.length > 0
                text: root.bridge.nameFor(root.number)
                color: Theme.accent
                font.pixelSize: 12
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8

        Rectangle {
            Layout.fillWidth: true
            height: 32
            radius: 6
            color: Theme.surface
            border.width: root.search.length > 0 ? 1 : 0
            border.color: Theme.accent
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                text: root.search || "Search contacts"
                color: root.search ? Theme.foreground : Theme.dim
                font.pixelSize: 12
            }
        }

        Rectangle {
            Layout.preferredWidth: 70
            height: 32
            radius: 6
            color: imp.containsMouse ? Theme.selection : Theme.surface
            Text {
                anchors.centerIn: parent
                text: "Import"
                color: Theme.dim
                font.pixelSize: 12
            }
            MouseArea {
                id: imp
                anchors.fill: parent
                hoverEnabled: true
                onClicked: picker.open()
            }
        }
    }

    FilePicker {
        id: picker
        onPicked: (path) => root.bridge.importContacts(path)
    }

    Text {
        Layout.fillWidth: true
        visible: root.bridge.lastImport.length > 0
        text: root.bridge.lastImport
        color: Theme.dim
        font.pixelSize: 11
        elide: Text.ElideRight
    }

    ContactList {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumHeight: 90
        bridge: root.bridge
        filter: root.search
        onChosen: (n) => { root.number = n; root.search = ""; }
    }

    Keypad {
        Layout.alignment: Qt.AlignHCenter
        onDigit: (d) => root.digit(d)
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8

        Rectangle {
            Layout.preferredWidth: 80
            height: 40
            radius: 8
            color: Theme.surface
            Text {
                anchors.centerIn: parent
                text: "Delete"
                color: Theme.dim
            }
            MouseArea { anchors.fill: parent; onClicked: root.backspace() }
        }

        Rectangle {
            id: callBtn
            Layout.fillWidth: true
            height: 40
            radius: 8
            enabled: root.number.length > 0 && root.bridge.connected
            opacity: enabled ? 1 : 0.4
            color: Theme.success
            Text {
                anchors.centerIn: parent
                text: "Call"
                color: Theme.background
                font.bold: true
            }
            MouseArea {
                anchors.fill: parent
                enabled: callBtn.enabled
                onClicked: root.call()
            }
        }
    }
}
