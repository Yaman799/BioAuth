import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme/Ui.js" as Ui

Rectangle {
    id: root
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    property url iconSource: ""
    property string title: ""
    property string detail: ""
    property string tone: "info"
    property string trailingText: ""

    implicitHeight: Math.max(68, content.implicitHeight + 22)
    Layout.minimumHeight: implicitHeight
    radius: 18
    color: Ui.colorToken(theme, "surface1")
    border.color: Ui.colorToken(theme, "border")
    border.width: 1

    RowLayout {
        id: content
        anchors.fill: parent
        anchors.margins: 13
        spacing: 12

        AssetIcon {
            sourceUrl: root.iconSource
            tone: root.tone
            Layout.preferredWidth: 38
            Layout.preferredHeight: 38
            Layout.alignment: Qt.AlignTop
            iconPadding: 8
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignVCenter
            spacing: 4

            Label {
                Layout.fillWidth: true
                text: root.title
                color: theme.text
                font.bold: true
                font.pixelSize: 14
                lineHeight: 1.06
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }

            Label {
                Layout.fillWidth: true
                text: root.detail
                color: theme.muted
                font.pixelSize: 12
                lineHeight: 1.08
                wrapMode: Text.Wrap
                maximumLineCount: 2
                elide: Text.ElideRight
            }
        }

        Label {
            visible: root.trailingText.length > 0
            Layout.maximumWidth: Math.max(82, root.width * 0.28)
            text: root.trailingText
            color: theme.muted
            font.pixelSize: 12
            font.bold: true
            horizontalAlignment: Text.AlignRight
            wrapMode: Text.Wrap
            maximumLineCount: 2
            elide: Text.ElideRight
        }
    }
}
