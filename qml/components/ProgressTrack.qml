import QtQuick

Item {
    id: root
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    property real value: 0
    property real maximum: 100
    property color fillColor: theme.primary
    implicitHeight: 16
    Rectangle {
        anchors.fill: parent
        radius: 8
        color: theme.progressTrackBg || theme.surface2
    }
    Rectangle {
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: Math.max(0, Math.min(parent.width, parent.width * (maximum <= 0 ? 0 : value / maximum)))
        height: parent.height
        radius: 8
        color: fillColor
    }
}
