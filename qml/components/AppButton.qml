import QtQuick
import QtQuick.Controls
import QtQuick.Window
import "../theme/Ui.js" as Ui

Button {
    id: control
    property string role: "neutral"
    property bool compact: false
    property string debugLabel: text
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    readonly property bool denseWindow: (Window.width || 0) > 0 && Window.width < 980
    readonly property int baseImplicitHeight: compact ? (denseWindow ? 38 : 40) : (denseWindow ? 44 : 46)
    readonly property int baseImplicitWidth: compact ? (denseWindow ? 96 : 108) : (denseWindow ? 128 : 148)
    readonly property int naturalTextWidth: Math.ceil(buttonTextMetrics.advanceWidth) + leftPadding + rightPadding + 18
    readonly property int maxNaturalWidth: denseWindow ? 260 : 320

    implicitHeight: Math.max(baseImplicitHeight, buttonLabel.implicitHeight + topPadding + bottomPadding + 6)
    implicitWidth: Math.max(baseImplicitWidth, Math.min(maxNaturalWidth, naturalTextWidth))
    hoverEnabled: true
    font.pixelSize: compact ? (denseWindow ? 12 : 13) : (denseWindow ? 14 : 15)
    font.bold: true
    leftPadding: compact ? 12 : 16
    rightPadding: compact ? 12 : 16
    topPadding: denseWindow ? 8 : 10
    bottomPadding: denseWindow ? 8 : 10
    scale: !enabled ? 1.0 : (down ? 0.985 : (hovered ? 1.012 : 1.0))

    TextMetrics {
        id: buttonTextMetrics
        text: control.text
        font.pixelSize: control.font.pixelSize
        font.bold: control.font.bold
    }

    Behavior on scale {
        NumberAnimation { duration: 110; easing.type: Easing.OutCubic }
    }

    onPressed: {
        try {
            if (backend.buttonSoundsMuted !== true)
                backend.playButtonSound(role)
        } catch (e) {}
    }

    function emitDebugClick() {
        try { backend.debugUiAction("button", (control.debugLabel || control.text || "button").toString()) } catch (e) {}
    }

    Component.onCompleted: {
        try { control.clicked.connect(control.emitDebugClick) } catch (e) {}
    }

    background: Rectangle {
        id: bg
        radius: denseWindow ? 14 : 16
        color: !control.enabled ? (theme.disabledBg || theme.surface2)
               : control.down ? Ui.rolePressedColor(theme, control.role)
               : control.hovered ? Ui.roleHoverColor(theme, control.role)
               : Ui.roleColor(theme, control.role)
        border.color: !control.enabled ? theme.border : Ui.roleBorderColor(theme, control.role)
        border.width: 1
        opacity: control.enabled ? 1.0 : 0.55

        Behavior on color { ColorAnimation { duration: 120 } }
        Behavior on border.color { ColorAnimation { duration: 120 } }

        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: parent.radius - 1
            color: "transparent"
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, control.hovered ? 0.13 : 0.07) }
                GradientStop { position: 0.32; color: Qt.rgba(1, 1, 1, 0.03) }
                GradientStop { position: 1.0; color: "transparent" }
            }
            opacity: control.enabled ? (control.down ? 0.1 : (control.hovered ? 1.0 : 0.72)) : 0.25
            Behavior on opacity { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
        }
    }

    contentItem: Label {
        id: buttonLabel
        text: control.text
        color: Ui.roleTextColor(theme, control.role)
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        font.pixelSize: control.font.pixelSize
        font.bold: control.font.bold
        wrapMode: Text.WordWrap
        maximumLineCount: control.compact ? 2 : 3
        elide: Text.ElideNone
        clip: false
    }
}
