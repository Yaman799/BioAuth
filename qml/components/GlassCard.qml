import QtQuick

Rectangle {
    id: root
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    radius: 28
    color: theme.glassBg || theme.surface
    border.color: theme.glassBorder || theme.border
    border.width: 1
    layer.enabled: visible
    layer.smooth: true

    Behavior on color { ColorAnimation { duration: 260; easing.type: Easing.OutCubic } }
    Behavior on border.color { ColorAnimation { duration: 320; easing.type: Easing.OutCubic } }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: parent.radius - 1
        color: "transparent"
        gradient: Gradient {
            GradientStop { position: 0.0; color: theme.glassHighlight || "#66ffffff" }
            GradientStop { position: 0.22; color: "transparent" }
            GradientStop { position: 1.0; color: "transparent" }
        }
        opacity: 0.12
    }
}
