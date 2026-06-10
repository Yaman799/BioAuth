import QtQuick
import QtQuick.Controls
import QtQuick.Window

TextField {
    id: field
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    readonly property bool denseWindow: (Window.width || 0) > 0 && Window.width < 980
    implicitHeight: denseWindow ? 48 : 52
    color: theme.text
    selectByMouse: true
    placeholderTextColor: theme.muted
    leftPadding: denseWindow ? 14 : 16
    rightPadding: denseWindow ? 14 : 16
    topPadding: denseWindow ? 10 : 12
    bottomPadding: denseWindow ? 10 : 12
    font.pixelSize: denseWindow ? 14 : 15
    background: Rectangle {
        radius: denseWindow ? 14 : 16
        color: theme.inputBg || theme.surface1
        border.color: field.activeFocus ? theme.accent : theme.border
        border.width: field.activeFocus ? 2 : 1
    }
}
