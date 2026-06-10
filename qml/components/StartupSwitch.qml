import QtQuick
import QtQuick.Controls

Item {
    id: control
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    property bool checked: false
    property string text: ""
    property string debugLabel: text
    signal toggled(bool checked)

    implicitWidth: 62
    implicitHeight: 34

    function requestToggle() {
        control.toggled(!control.checked)
    }

    function emitDebugToggle(nextChecked) {
        try {
            var label = (control.debugLabel || control.text || "toggle").toString()
            backend.debugUiAction("toggle", label + " -> " + (nextChecked ? "enabled" : "disabled"))
        } catch (e) {
        }
    }

    Component.onCompleted: {
        try {
            control.toggled.connect(control.emitDebugToggle)
        } catch (e) {
        }
    }

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: control.checked ? theme.accent : (theme.switchOffBg || theme.surface2)
        border.color: control.checked ? theme.accent : theme.border
        border.width: 1

        Behavior on color { ColorAnimation { duration: 140 } }
        Behavior on border.color { ColorAnimation { duration: 140 } }

        Rectangle {
            width: 28
            height: 28
            radius: 14
            y: 3
            x: control.checked ? parent.width - width - 3 : 3
            color: "#ffffff"
            border.color: "#d3dbe8"
            border.width: 1
            Behavior on x { NumberAnimation { duration: 180 } }
        }
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: control.requestToggle()
    }

    TapHandler {
        onTapped: control.requestToggle()
    }

    Keys.onSpacePressed: control.requestToggle()
    Keys.onReturnPressed: control.requestToggle()
    focus: activeFocus
}
