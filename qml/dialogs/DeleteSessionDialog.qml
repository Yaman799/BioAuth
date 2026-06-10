import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Dialog {
    id: root
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property string sessionPath: ""
    signal confirmed(string sessionPath)
    modal: true
    anchors.centerIn: Overlay.overlay
    width: Math.max(320, Math.min(500, (rootWindow ? rootWindow.width : 560) - 32))
    padding: 0
    background: GlassCard { }

    contentItem: ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 14

        Rectangle {
            Layout.fillWidth: true
            radius: 18
            color: theme.dangerBg
            border.color: theme.danger
            border.width: 1
            implicitHeight: dangerSummary.implicitHeight + 24

            ColumnLayout {
                id: dangerSummary
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8
                Label { text: rootWindow.trx("حذف الجلسة من الأرشيف", "Delete session from archive"); color: theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                Label { text: rootWindow.trx("سيتم حذف هذه الجلسة من التخزين المحلي فقط. لا يمكن التراجع عن العملية بعد التأكيد.", "This removes the session from local archive storage only. The action cannot be undone after confirmation."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            radius: 16
            color: theme.surface4
            border.color: theme.border
            border.width: 1
            implicitHeight: pathText.implicitHeight + 24

            Label {
                id: pathText
                anchors.fill: parent
                anchors.margins: 12
                text: root.sessionPath
                color: theme.muted
                wrapMode: Text.WrapAnywhere
                verticalAlignment: Text.AlignVCenter
            }
        }

        Flow {
            Layout.fillWidth: true
            spacing: 10
            layoutDirection: Qt.RightToLeft
            AppButton {
                text: rootWindow.trx("حذف", "Delete")
                role: "danger"
                onClicked: {
                    root.confirmed(root.sessionPath)
                    root.close()
                }
            }
            AppButton { text: rootWindow.trx("إلغاء", "Cancel"); role: "neutral"; onClicked: root.close() }
        }
    }
}
