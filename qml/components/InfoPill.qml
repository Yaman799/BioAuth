import QtQuick
import QtQuick.Controls
import QtQuick.Window
import "../theme/Ui.js" as Ui

Rectangle {
    id: root
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    property string textValue: ""
    property string pillTone: "neutral"
    readonly property bool denseWindow: (Window.width || 0) > 0 && Window.width < 980
    readonly property real textMaxWidth: denseWindow ? 180 : 260
    readonly property color baseToneColor: Ui.roleColor(theme, pillTone)
    radius: denseWindow ? 14 : 16
    implicitWidth: Math.min(pillLabel.implicitWidth + (denseWindow ? 20 : 24), textMaxWidth + (denseWindow ? 20 : 24))
    implicitHeight: Math.max(denseWindow ? 28 : 32, pillLabel.implicitHeight + (denseWindow ? 12 : 14))
    color: Qt.rgba(baseToneColor.r, baseToneColor.g, baseToneColor.b, theme.isDark ? 0.18 : 0.14)
    border.color: Qt.rgba(baseToneColor.r, baseToneColor.g, baseToneColor.b, theme.isDark ? 0.42 : 0.28)

    Label {
        id: pillLabel
        anchors.centerIn: parent
        width: Math.min(implicitWidth, root.textMaxWidth)
        text: root.textValue
        color: theme.text
        font.pixelSize: root.denseWindow ? 12 : 13
        font.bold: true
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
    }
}
