import QtQuick
import QtQuick.Controls

CheckBox {
    id: control
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    property bool compact: false
    property string debugLabel: text
    implicitWidth: indicator.implicitWidth + ((text || "").length > 0 ? contentItem.implicitWidth + spacing : 0)
    implicitHeight: Math.max(indicator.implicitHeight, contentItem.implicitHeight)
    spacing: compact ? 8 : 10
    hoverEnabled: true

    function emitDebugToggle(nextChecked) {
        try {
            var label = (control.debugLabel || control.text || "checkbox").toString()
            backend.debugUiAction("checkbox", label + " -> " + (nextChecked ? "enabled" : "disabled"))
        } catch (e) {}
    }

    Component.onCompleted: {
        try { control.toggled.connect(control.emitDebugToggle) } catch (e) {}
    }

    indicator: Rectangle {
        implicitWidth: compact ? 22 : 24
        implicitHeight: compact ? 22 : 24
        radius: 8
        color: !control.enabled ? (theme.checkboxDisabledBg || theme.surface2)
               : control.checked ? theme.info
               : (control.hovered ? (theme.checkboxHoverBg || theme.surface1) : (theme.checkboxBg || theme.surface))
        border.width: 1
        border.color: !control.enabled ? theme.border
                    : control.checked ? Qt.lighter(theme.info, 1.08)
                    : (control.hovered ? Qt.rgba(theme.info.r, theme.info.g, theme.info.b, 0.65) : theme.border)

        Rectangle {
            anchors.centerIn: parent
            width: parent.width - 8
            height: parent.height - 8
            radius: 6
            color: Qt.rgba(1, 1, 1, control.checked ? 0.16 : 0.0)
            visible: control.checked
        }

        Label {
            anchors.centerIn: parent
            text: "✓"
            color: "#ffffff"
            font.pixelSize: compact ? 12 : 13
            font.bold: true
            visible: control.checked
        }

        Behavior on color { ColorAnimation { duration: 120 } }
        Behavior on border.color { ColorAnimation { duration: 120 } }
        Behavior on scale { NumberAnimation { duration: 100; easing.type: Easing.OutCubic } }
        scale: control.down ? 0.94 : (control.hovered ? 1.03 : 1.0)
    }

    contentItem: Label {
        text: control.text
        visible: (control.text || "").length > 0
        color: theme.text
        verticalAlignment: Text.AlignVCenter
        leftPadding: control.indicator.implicitWidth + control.spacing
        elide: Text.ElideRight
        wrapMode: Text.NoWrap
        font.pixelSize: compact ? 13 : 14
        font.bold: true
    }

    background: Item { }
}
