import QtQuick
import QtQuick.Layouts
import ".."

ColumnLayout {
    id: root
    required property var bridge
    signal chosen(string number)

    property string filter: ""
    spacing: 8

    // Arabic has several ways to write the same name: alef carries hamza or
    // madda, final ya and alef maqsura are interchangeable in practice, ta
    // marbuta is often typed as ha, and tashkeel may or may not be present.
    // Fold all of that away so searching finds what the user means.
    function fold(text) {
        return text.toLowerCase()
            .replace(/[\u064B-\u0652\u0670\u0640]/g, "")  // tashkeel + tatweel
            .replace(/[\u0622\u0623\u0625\u0671]/g, "\u0627")  // alef variants
            .replace(/\u0649/g, "\u064A")                  // alef maqsura -> ya
            .replace(/\u0629/g, "\u0647")                  // ta marbuta -> ha
            .replace(/[\u0624\u0626]/g, "\u0621");         // hamza carriers
    }

    function matches(c) {
        const f = fold(root.filter.trim());
        if (f.length === 0) return true;
        if (fold(c.name).indexOf(f) >= 0) return true;
        // Only compare digits when the filter actually has some: indexOf("")
        // returns 0, which would otherwise match every contact.
        const digits = f.replace(/\D/g, "");
        return digits.length > 0
            && c.number.replace(/\D/g, "").indexOf(digits) >= 0;
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        radius: 8
        color: Theme.surface

        Text {
            anchors.centerIn: parent
            width: parent.width - 32
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            visible: root.bridge.contacts.count === 0
            text: "No contacts yet.\n\nYour phone refuses Bluetooth phonebook access, "
                + "so import a .vcf or .csv export instead."
            color: Theme.dim
            font.pixelSize: 12
        }

        ListView {
            id: list
            anchors.fill: parent
            anchors.margins: 4
            clip: true
            visible: root.bridge.contacts.count > 0
            model: root.bridge.contacts

            delegate: Rectangle {
                required property var model
                required property int index
                width: list.width
                height: visible ? 44 : 0
                visible: root.matches(model)
                radius: 6
                color: hover.containsMouse ? Theme.selection : "transparent"

                ColumnLayout {
                    anchors.left: parent.left
                    anchors.leftMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 0
                    Text {
                        text: model.name
                        color: Theme.foreground
                        font.pixelSize: 14
                    }
                    Text {
                        text: model.number
                        color: Theme.dim
                        font.pixelSize: 11
                    }
                }

                MouseArea {
                    id: hover
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: root.chosen(model.number)
                }
            }
        }
    }
}
