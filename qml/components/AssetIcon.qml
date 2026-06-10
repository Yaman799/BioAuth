import QtQuick
import "../theme/Ui.js" as Ui

Item {
    id: root
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    property url sourceUrl: ""
    property string tone: "info"
    property bool showChrome: true
    property real iconPadding: 8
    property real chromeOpacity: theme.isDark ? 0.075 : 0.065

    readonly property color accentColor: Ui.roleColor(theme, tone)
    readonly property color badgeSurface: Ui.colorToken(theme, "surface1")
    readonly property color badgeBorder: Ui.colorToken(theme, "border")
    readonly property real badgeRadius: Math.min(width, height) / 3.2

    implicitWidth: 38
    implicitHeight: 38

    Rectangle {
        anchors.fill: parent
        radius: root.badgeRadius
        visible: root.showChrome
        color: root.badgeSurface
        opacity: root.enabled ? 0.94 : 0.50
        border.color: "transparent"
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: Math.max(0, root.badgeRadius - 1)
        visible: root.showChrome
        color: root.accentColor
        opacity: root.enabled ? root.chromeOpacity : root.chromeOpacity * 0.45
        border.color: "transparent"
    }

    Rectangle {
        anchors.fill: parent
        radius: root.badgeRadius
        visible: root.showChrome
        color: "transparent"
        border.color: root.badgeBorder
        border.width: 1
        opacity: theme.isDark ? 0.78 : 0.60
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: Math.max(0, root.badgeRadius - 1)
        visible: root.showChrome
        color: "transparent"
        border.color: root.accentColor
        border.width: 1
        opacity: root.enabled ? (theme.isDark ? 0.14 : 0.10) : 0.06
    }

    Image {
        anchors.fill: parent
        anchors.margins: root.iconPadding
        source: root.sourceUrl
        fillMode: Image.PreserveAspectFit
        smooth: true
        asynchronous: true
        mipmap: false
        cache: true
        opacity: root.enabled ? 0.88 : 0.42
    }
}
