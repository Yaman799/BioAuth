import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Dialog {
    id: root
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property string passwordDraft: ""
    signal confirmed(string password)
    modal: true
    anchors.centerIn: Overlay.overlay
    width: Math.max(320, Math.min(460, (rootWindow ? rootWindow.width : 540) - 32))
    background: GlassCard { }
    contentItem: ColumnLayout {
        spacing: 16
        Label { text: backend.tr("confirm_delete"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Flow {
            Layout.fillWidth: true
            spacing: 10
            layoutDirection: Qt.RightToLeft
            AppButton {
                text: backend.tr("delete_account")
                role: "danger"
                onClicked: {
                    root.confirmed(root.passwordDraft)
                    root.close()
                }
            }
            AppButton { text: rootWindow.trx("إلغاء", "Cancel"); role: "neutral"; onClicked: root.close() }
        }
    }
    padding: 20
}
