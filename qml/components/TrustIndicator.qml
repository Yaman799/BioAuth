import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme/Ui.js" as Ui

Item {
    id: root
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    property string tone: "info"
    property string headline: ""
    property string subline: ""
    property real diameter: 230
    property bool animated: false
    property bool pulseFlip: false
    property bool detailOutside: false
    property string compactHeadline: ""
    property string compactSubline: ""
    property string detailText: ""
    property int headlinePixelSize: Math.max(24, Math.round(root.diameter * 0.11))
    property int sublinePixelSize: Math.max(12, Math.round(root.diameter * 0.053))
    readonly property string resolvedHeadline: (root.compactHeadline || root.headline || "").trim()
    readonly property string resolvedSubline: (root.compactSubline || root.subline || "").trim()
    readonly property string resolvedDetailText: (root.detailText || "").trim()
    readonly property bool showOutsideDetail: root.detailOutside && root.resolvedDetailText.length > 0
    readonly property color accentColor: Ui.auraColor(theme, root.tone)
    readonly property color accentSoftColor: Qt.lighter(accentColor, 1.18)
    readonly property color accentDeepColor: Qt.darker(accentColor, 1.22)
    readonly property color panelColor: theme.trustPanel || theme.surface
    readonly property color bezelColor: theme.trustBezel || theme.surface1
    readonly property color surfaceColor: theme.trustSurface || theme.surface3
    readonly property color stateDotColor: root.animated
                                           ? (root.pulseFlip ? root.accentSoftColor : root.accentColor)
                                           : root.accentColor

    implicitWidth: diameter
    implicitHeight: root.diameter + (root.showOutsideDetail ? detailLabel.implicitHeight + Math.max(12, Math.round(root.diameter * 0.05)) : 0)
    width: implicitWidth
    height: implicitHeight

    Timer {
        interval: 1400
        repeat: true
        running: root.visible && root.animated
        onTriggered: root.pulseFlip = !root.pulseFlip
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        width: root.diameter
        height: root.diameter
        radius: width / 2
        color: "transparent"
        border.width: Math.max(2, Math.round(root.diameter * 0.013))
        border.color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.46)
        antialiasing: false
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: root.diameter * 0.05
        width: root.diameter * 0.9
        height: width
        radius: width / 2
        color: root.bezelColor
        border.width: 1
        border.color: Qt.rgba(root.accentDeepColor.r, root.accentDeepColor.g, root.accentDeepColor.b, 0.22)
        antialiasing: false
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: root.diameter * 0.09
        width: root.diameter * 0.82
        height: width
        radius: width / 2
        color: root.panelColor
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, theme.isDark ? 0.05 : 0.22)
        antialiasing: false
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: Math.round(root.diameter * 0.12)
        width: root.diameter * 0.24
        height: Math.max(8, Math.round(root.diameter * 0.03))
        radius: Math.round(height / 2)
        color: Qt.rgba(root.accentSoftColor.r, root.accentSoftColor.g, root.accentSoftColor.b, 0.92)
        antialiasing: false
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: Math.round(root.diameter * 0.16)
        width: root.diameter * 0.32
        height: 1
        color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.32)
        antialiasing: false
    }

    Rectangle {
        id: stateDot
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.rightMargin: Math.round(root.diameter * 0.15)
        anchors.topMargin: Math.round(root.diameter * 0.18)
        width: Math.max(10, Math.round(root.diameter * 0.055))
        height: width
        radius: width / 2
        color: root.stateDotColor
        border.width: 1
        border.color: Qt.rgba(root.panelColor.r, root.panelColor.g, root.panelColor.b, theme.isDark ? 0.88 : 0.72)
        antialiasing: false
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: Math.round(root.diameter * 0.23)
        width: root.diameter * 0.26
        height: root.diameter * 0.22
        radius: Math.max(10, Math.round(root.diameter * 0.05))
        color: root.surfaceColor
        border.width: 1
        border.color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.36)
        antialiasing: false

        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.top
            anchors.topMargin: Math.max(10, Math.round(root.diameter * 0.034))
            width: parent.width * 0.44
            height: Math.max(3, Math.round(root.diameter * 0.015))
            radius: Math.round(height / 2)
            color: Qt.rgba(root.accentSoftColor.r, root.accentSoftColor.g, root.accentSoftColor.b, 0.92)
            antialiasing: false
        }

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: Math.max(12, Math.round(root.diameter * 0.038))
            spacing: Math.max(4, Math.round(root.diameter * 0.02))

            Repeater {
                model: 3
                Rectangle {
                    width: Math.max(6, Math.round(root.diameter * 0.027))
                    height: Math.max(16, Math.round(root.diameter * 0.07)) + (index * Math.max(3, Math.round(root.diameter * 0.012)))
                    radius: Math.round(width / 2)
                    color: index === 1 ? root.accentSoftColor : root.accentColor
                    antialiasing: false
                }
            }
        }
    }

    ColumnLayout {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: Math.round(root.diameter * 0.56)
        width: root.diameter * 0.5
        spacing: Math.max(4, Math.round(root.diameter * 0.018))

        Label {
            visible: root.resolvedHeadline.length > 0
            text: root.resolvedHeadline
            color: theme.text
            font.pixelSize: root.headlinePixelSize
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignHCenter
        }

        Label {
            visible: root.resolvedSubline.length > 0
            text: root.resolvedSubline
            color: theme.muted
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
            font.pixelSize: root.sublinePixelSize
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignHCenter
        }
    }

    Label {
        id: detailLabel
        visible: root.showOutsideDetail
        anchors.top: parent.top
        anchors.topMargin: root.diameter + Math.max(10, Math.round(root.diameter * 0.04))
        anchors.horizontalCenter: parent.horizontalCenter
        width: root.diameter * 0.82
        text: root.resolvedDetailText
        color: theme.muted
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        font.pixelSize: Math.max(12, Math.round(root.diameter * 0.05))
    }
}
