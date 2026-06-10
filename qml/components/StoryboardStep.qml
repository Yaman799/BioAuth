import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme/Ui.js" as Ui

Rectangle {
    id: root
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    property int stepNumber: 1
    property string title: ""
    property string detail: ""
    property string stateText: ""
    property string tone: "neutral"
    property bool active: false
    readonly property color accentColor: Ui.roleColor(theme, tone)

    implicitHeight: Math.max(76, stepContent.implicitHeight + 22)
    Layout.minimumHeight: implicitHeight
    radius: 20
    color: active ? Qt.rgba(accentColor.r, accentColor.g, accentColor.b, 0.12) : theme.surface1
    border.color: active ? Qt.rgba(accentColor.r, accentColor.g, accentColor.b, 0.46) : theme.border
    border.width: 1

    RowLayout {
        id: stepContent
        anchors.fill: parent
        anchors.margins: 12
        spacing: 12

        Rectangle {
            Layout.preferredWidth: 36
            Layout.preferredHeight: 36
            radius: 18
            color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.18)
            border.color: Qt.rgba(root.accentColor.r, root.accentColor.g, root.accentColor.b, 0.42)
            Label {
                anchors.centerIn: parent
                text: root.stepNumber
                color: theme.text
                font.bold: true
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Label {
                    Layout.fillWidth: true
                    text: root.title
                    color: theme.text
                    font.bold: true
                    font.pixelSize: 13
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                }
                InfoPill {
                    visible: root.stateText.length > 0
                    textValue: root.stateText
                    pillTone: root.tone
                }
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
    }
}
