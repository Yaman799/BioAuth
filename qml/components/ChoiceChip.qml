import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: chip
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    property string titleText: ""
    property string descriptionText: ""
    property string debugLabel: titleText
    property bool selected: false
    property string accentColor: theme.accent
    signal chosen()

    function emitDebugChoice() {
        try { backend.debugUiAction("choice", (chip.debugLabel || chip.titleText || "choice").toString()) } catch (e) {}
    }

    Component.onCompleted: {
        try { chip.chosen.connect(chip.emitDebugChoice) } catch (e) {}
    }
    Layout.fillWidth: true
    radius: 18
    implicitHeight: chipContent.implicitHeight + 26
    color: selected ? (theme.chipSelectedBg || theme.surface2) : (theme.chipBg || theme.surface1)
    border.color: selected ? accentColor : theme.border
    border.width: selected ? 2 : 1

    Behavior on color { ColorAnimation { duration: 220 } }
    Behavior on border.color { ColorAnimation { duration: 220 } }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            try {
                if (backend.buttonSoundsMuted !== true)
                    backend.playButtonSound("details")
            } catch (e) {}
            chip.chosen()
        }
    }

    RowLayout {
        id: chipContent
        anchors.fill: parent
        anchors.margins: 14
        spacing: 12

        Rectangle {
            implicitWidth: 18
            implicitHeight: 18
            radius: 9
            color: chip.selected ? chip.accentColor : "transparent"
            border.color: chip.selected ? chip.accentColor : theme.border
            border.width: 2
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4
            Label {
                text: chip.titleText
                color: theme.text
                font.bold: true
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
            Label {
                text: chip.descriptionText
                color: theme.muted
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
        }
    }
}
