import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: card
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    property string titleText: ""
    property string descriptionText: ""
    property string badgeText: ""
    property string helpText: ""
    property string accentColor: theme.accent
    property bool selected: false
    property bool compact: false
    property string debugLabel: titleText
    signal chosen()

    Layout.fillWidth: true
    radius: compact ? 18 : 20
    implicitHeight: content.implicitHeight + (compact ? 24 : 28)
    color: selected ? (theme.chipSelectedBg || theme.surface2) : (theme.chipBg || theme.surface1)
    border.color: selected ? accentColor : theme.border
    border.width: selected ? 2 : 1

    function emitDebugChoice() {
        try { backend.debugUiAction("choice", (card.debugLabel || card.titleText || "choice").toString()) } catch (e) {}
    }

    Component.onCompleted: {
        try { card.chosen.connect(card.emitDebugChoice) } catch (e) {}
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            try {
                if (backend.buttonSoundsMuted !== true)
                    backend.playButtonSound("details")
            } catch (e) {}
            card.chosen()
        }
    }

    ColumnLayout {
        id: content
        anchors.fill: parent
        anchors.margins: compact ? 14 : 16
        spacing: compact ? 10 : 12

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Rectangle {
                implicitWidth: compact ? 34 : 38
                implicitHeight: implicitWidth
                radius: 12
                color: card.selected ? card.accentColor : theme.iconActiveBg
                border.color: card.selected ? card.accentColor : theme.border
                border.width: 1
                Label {
                    anchors.centerIn: parent
                    text: card.badgeText
                    color: card.selected ? "#ffffff" : theme.muted
                    font.pixelSize: compact ? 12 : 13
                    font.bold: true
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Label {
                    text: card.titleText
                    color: theme.text
                    font.bold: true
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
                Label {
                    text: card.descriptionText
                    color: theme.muted
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
            }

            ToolButton {
                visible: card.helpText.length > 0
                text: "?"
                font.bold: true
                font.pixelSize: compact ? 12 : 13
                implicitWidth: compact ? 28 : 30
                implicitHeight: implicitWidth
                padding: 0
                background: Rectangle {
                    radius: width / 2
                    color: theme.surface2
                    border.color: theme.border
                    border.width: 1
                }
                contentItem: Label {
                    text: parent.text
                    color: theme.text
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    font: parent.font
                }
                ToolTip.visible: hovered
                ToolTip.text: card.helpText
                ToolTip.delay: 100
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            Rectangle {
                implicitWidth: 18
                implicitHeight: 18
                radius: 9
                color: card.selected ? card.accentColor : "transparent"
                border.color: card.selected ? card.accentColor : theme.border
                border.width: 2
            }
            Label {
                Layout.fillWidth: true
                text: card.selected ? qsTr("Selected") : qsTr("Tap to choose")
                color: card.selected ? card.accentColor : theme.muted
                font.pixelSize: compact ? 12 : 13
                font.bold: true
                wrapMode: Text.Wrap
            }
        }
    }
}
