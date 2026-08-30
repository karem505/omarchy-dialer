import QtQuick
import QtQuick.Layouts
import ".."

GridLayout {
    id: root
    signal digit(string d)

    columns: 3
    rowSpacing: 8
    columnSpacing: 8

    Repeater {
        model: ["1","2","3","4","5","6","7","8","9","*","0","#"]
        delegate: Rectangle {
            required property string modelData
            Layout.preferredWidth: 64
            Layout.preferredHeight: 48
            radius: 8
            color: mouse.pressed ? Theme.selection : Theme.surface
            Text {
                anchors.centerIn: parent
                text: parent.modelData
                color: Theme.foreground
                font.pixelSize: 18
            }
            MouseArea {
                id: mouse
                anchors.fill: parent
                onClicked: root.digit(parent.modelData)
            }
        }
    }
}
