import QtQuick
import QtQuick.Controls
import "../../theme/Ui.js" as Ui

Rectangle {
    id: root

    property var theme: backend.theme
    property string textValue: ""
    property bool selected: false
    property string tone: "info"
    property int chipHeight: 40

    signal chosen()

    width: chipLabel.implicitWidth + 34
    height: chipHeight
    radius: 18
    color: root.selected ? Ui.colorToken(root.theme, "chipSelectedBg") : Ui.colorToken(root.theme, "chipBg")
    border.color: root.selected ? Ui.roleColor(root.theme, root.tone) : Ui.colorToken(root.theme, "border")
    border.width: root.selected ? 2 : 1

    Label {
        id: chipLabel
        anchors.centerIn: parent
        text: root.textValue
        color: root.theme.text
        font.pixelSize: 13
        font.bold: true
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.chosen()
    }
}
