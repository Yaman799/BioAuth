import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

ColumnLayout {
    id: root
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    property string title: ""
    property string subtitle: ""
    readonly property bool denseWindow: (Window.width || 0) > 0 && Window.width < 980
    spacing: 4

    Label {
        text: root.title
        color: theme.text
        font.pixelSize: root.denseWindow ? 20 : 24
        font.bold: true
        wrapMode: Text.Wrap
        Layout.fillWidth: true
    }
    Label {
        text: root.subtitle
        color: theme.muted
        wrapMode: Text.Wrap
        Layout.fillWidth: true
    }
}
