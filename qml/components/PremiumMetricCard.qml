import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme/Ui.js" as Ui

GlassCard {
    id: card
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    property url iconSource: ""
    property string title: ""
    property string value: ""
    property string detail: ""
    property string tone: "info"
    property bool compact: false
    readonly property color accentColor: Ui.roleColor(theme, tone)

    implicitHeight: Math.max(compact ? 116 : 132, metricContent.implicitHeight + (compact ? 28 : 32))
    Layout.minimumHeight: implicitHeight
    clip: false

    Rectangle {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 3
        radius: 2
        color: card.accentColor
        opacity: theme.isDark ? 0.42 : 0.34
    }

    RowLayout {
        id: metricContent
        anchors.fill: parent
        anchors.margins: compact ? 13 : 16
        spacing: compact ? 11 : 13

        AssetIcon {
            sourceUrl: card.iconSource
            tone: card.tone
            Layout.preferredWidth: compact ? 38 : 40
            Layout.preferredHeight: compact ? 38 : 40
            Layout.alignment: Qt.AlignTop
            iconPadding: compact ? 7 : 8
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            spacing: compact ? 4 : 5

            Label {
                Layout.fillWidth: true
                text: card.title
                color: theme.muted
                font.pixelSize: compact ? 12 : 13
                font.bold: true
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }

            Label {
                Layout.fillWidth: true
                text: card.value
                color: theme.text
                font.pixelSize: compact ? 16 : 19
                font.bold: true
                lineHeight: 1.04
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }

            Label {
                Layout.fillWidth: true
                text: card.detail
                color: theme.muted
                font.pixelSize: compact ? 11 : 12
                lineHeight: 1.08
                wrapMode: Text.Wrap
                maximumLineCount: compact ? 2 : 4
                elide: Text.ElideRight
            }
        }
    }
}
