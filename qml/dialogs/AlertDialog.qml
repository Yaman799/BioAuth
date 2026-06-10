import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Dialog {
    id: root
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property string tone: "info"
    property string body: ""
    modal: true
    anchors.centerIn: Overlay.overlay
    width: Math.max(320, Math.min(500, (rootWindow ? rootWindow.width : 560) - 32))
    height: Math.min(520, Math.max(220, (rootWindow ? rootWindow.height : 700) - 40))
    background: GlassCard { }
    header: Item {
        implicitHeight: titleColumn.implicitHeight + 32
        RowLayout {
            anchors.fill: parent
            anchors.margins: 22
            spacing: 14
            Rectangle {
                implicitWidth: 46
                implicitHeight: 46
                radius: 16
                color: rootWindow.toneColor(root.tone)
                Label {
                    anchors.centerIn: parent
                    text: "!"
                    color: "#ffffff"
                    font.pixelSize: 24
                    font.bold: true
                }
            }
            ColumnLayout {
                id: titleColumn
                Layout.fillWidth: true
                spacing: 4
                Label { text: root.title; color: theme.text; font.pixelSize: 24; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Label { text: rootWindow.trx("إشعار أمني", "Security message"); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            }
        }
    }
    contentItem: ColumnLayout {
        spacing: 16
        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredHeight: Math.min(360, bodyLabel.implicitHeight + 12)
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            Label {
                id: bodyLabel
                width: parent.width
                text: root.body
                color: theme.text
                wrapMode: Text.Wrap
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            AppButton {
                text: "OK"
                role: root.tone === "error" ? "danger" : root.tone === "warning" ? "warn" : "info"
                onClicked: root.close()
            }
        }
    }
    padding: 22
}
