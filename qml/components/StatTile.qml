import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

GlassCard {
    id: tile
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    property string title: ""
    property string value: ""
    property string subtitle: ""
    property string accentColor: theme.primary
    property string badge: ""
    readonly property bool denseWindow: (Window.width || 0) > 0 && Window.width < 980
    implicitHeight: contentColumn.implicitHeight + (denseWindow ? 32 : 40)

    Rectangle {
        anchors.left: parent.left
        anchors.leftMargin: denseWindow ? 14 : 16
        anchors.top: parent.top
        anchors.topMargin: denseWindow ? 16 : 18
        width: 7
        height: parent.height - (denseWindow ? 32 : 36)
        radius: 4
        color: tile.accentColor
        opacity: 0.95
    }

    ColumnLayout {
        id: contentColumn
        anchors.fill: parent
        anchors.margins: denseWindow ? 18 : 22
        anchors.leftMargin: denseWindow ? 30 : 34
        spacing: denseWindow ? 6 : 8

        RowLayout {
            Layout.fillWidth: true
            Label {
                text: tile.title
                color: theme.muted
                font.pixelSize: denseWindow ? 13 : 14
                font.bold: true
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
            InfoPill {
                visible: tile.badge.length > 0
                textValue: tile.badge
                pillTone: tile.badge.length > 0 ? "details" : "neutral"
            }
        }
        Label {
            text: tile.value
            color: theme.text
            font.pixelSize: denseWindow ? 24 : 30
            font.bold: true
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }
        Label {
            text: tile.subtitle
            color: theme.muted
            wrapMode: Text.Wrap
            Layout.fillWidth: true
        }
    }
}
