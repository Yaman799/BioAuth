import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Dialog {
    id: root
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property string bodyText: ""
    property string confirmText: "OK"
    property string cancelText: "Cancel"
    property string tone: "danger"
    signal confirmed()
    modal: true
    anchors.centerIn: Overlay.overlay
    width: Math.max(320, Math.min(460, (rootWindow ? rootWindow.width : 540) - 32))
    background: GlassCard { }
    contentItem: ColumnLayout {
        spacing: 16
        Label { text: root.bodyText; color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Flow {
            Layout.fillWidth: true
            spacing: 10
            layoutDirection: Qt.RightToLeft
            AppButton {
                text: root.confirmText
                role: root.tone
                onClicked: {
                    root.confirmed()
                    root.close()
                }
            }
            AppButton { text: root.cancelText; role: "neutral"; onClicked: root.reject() }
        }
    }
    padding: 20
}
