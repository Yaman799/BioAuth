import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: card

    property var theme
    property string titleText: ""
    property string noteText: ""
    property string iconText: "•"
    property string statusText: ""
    property bool selected: false
    signal chosen()

    Layout.fillWidth: true
    implicitHeight: cardContent.implicitHeight + 24
    radius: 20
    color: selected ? (theme.navActiveBg || theme.surface2) : theme.surface1
    border.color: selected ? theme.accent : theme.border
    border.width: 1

    RowLayout {
        id: cardContent
        anchors.fill: parent
        anchors.margins: 12
        spacing: 12

        Rectangle {
            implicitWidth: 42
            implicitHeight: 42
            radius: 14
            color: selected ? theme.accent : theme.iconActiveBg
            border.color: selected ? theme.accent : theme.border
            border.width: 1
            Label {
                anchors.centerIn: parent
                text: card.iconText
                color: selected ? "#ffffff" : theme.muted
                font.pixelSize: 18
                font.bold: true
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4
            Label {
                Layout.fillWidth: true
                text: card.titleText
                color: theme.text
                font.bold: true
                wrapMode: Text.Wrap
            }
            Label {
                Layout.fillWidth: true
                text: card.noteText
                color: theme.muted
                font.pixelSize: 12
                wrapMode: Text.Wrap
            }
        }

        Rectangle {
            visible: card.statusText.length > 0
            implicitWidth: statusLabel.implicitWidth + 18
            implicitHeight: 28
            radius: 14
            color: selected ? theme.surface1 : theme.surface2
            border.color: selected ? theme.accent : theme.border
            border.width: 1
            Label {
                id: statusLabel
                anchors.centerIn: parent
                text: card.statusText
                color: selected ? theme.text : theme.muted
                font.pixelSize: 11
                font.bold: selected
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: card.chosen()
    }
}
