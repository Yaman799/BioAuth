import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"

GlassCard {
    id: card
    property var controller
    property var theme
    property var rootWindow
    property string feedbackText: ""
    property string pairingJson: ""
    property string qrImageDataUri: ""
    property var refreshedState: ({})
    property var lastResult: ({})
    property bool trustedLanConfirmed: false
    function trx(arText, enText) { return controller ? controller.trx(arText, enText) : enText }
    function stateText() {
        var state = (card.refreshedState && card.refreshedState.running !== undefined) ? card.refreshedState : (backend.companionApiState || ({}))
        if (state.running === true) return trx("يعمل", "Running") + " • " + String(state.host || "?") + ":" + String(state.port || "?")
        return trx("متوقف", "Stopped")
    }
    function pairedCountText() {
        var state = (card.refreshedState && card.refreshedState.running !== undefined) ? card.refreshedState : (backend.companionApiState || ({}))
        return String(state.pairedDeviceCount || 0)
    }
    function generateLanPayload() {
        var result = backend.createCompanionLanPairingPayload(card.trustedLanConfirmed)
        card.lastResult = result || ({})
        if (result && result.ok === true) {
            card.pairingJson = String(result.pairingJson || "")
            card.qrImageDataUri = String(result.qrPngDataUri || "")
            if (result.qrAvailable === true) {
                card.feedbackText = trx("تم إنشاء QR و JSON ربط صالح للهاتف. الرمز ينتهي تلقائيًا.", "Pairing QR and JSON generated for Android. The code expires automatically.")
            } else {
                card.feedbackText = trx("تم إنشاء JSON الربط، لكن لم يتم إنشاء QR. استخدم النسخ اليدوي.", "Pairing JSON generated, but QR creation is unavailable. Use manual copy/paste.") + " " + String(result.qrError || "")
            }
        } else {
            card.qrImageDataUri = ""
            card.feedbackText = trx("تعذر إنشاء ربط الهاتف.", "Could not prepare phone pairing.") + " " + String((result && (result.message || result.user_safe_reason || result.error)) || "")
        }
    }

    Timer {
        interval: 2000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: {
            card.refreshedState = backend.companionApiState || ({})
        }
    }

    Layout.fillWidth: true
    Layout.columnSpan: parent ? parent.columns : 1
    implicitHeight: companionContent.implicitHeight + 40

    ColumnLayout {
        id: companionContent
        anchors.fill: parent
        anchors.margins: 20
        spacing: 14

        SectionHeader {
            title: trx("Mobile Companion", "Mobile Companion")
            subtitle: trx("ربط تطبيق Android كتطبيق قراءة فقط يعرض حالة BioAuth الحقيقية بدون أي صلاحيات تحكم.", "Pair the Android app as a read-only companion. Scan the QR, pair the phone, then view live desktop status on mobile.")
        }

        Flow {
            Layout.fillWidth: true
            spacing: 10
            InfoPill { textValue: trx("API", "API") + ": " + card.stateText(); pillTone: (card.refreshedState && card.refreshedState.running === true) ? "success" : "warn" }
            InfoPill { textValue: trx("Paired", "Paired") + ": " + card.pairedCountText(); pillTone: Number(card.pairedCountText()) > 0 ? "success" : "neutral" }
            InfoPill { textValue: trx("Read-only", "Read-only"); pillTone: "success" }
                    }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: companionActions.implicitHeight + 28
            radius: 18
            color: theme.surface1
            border.color: theme.border
            border.width: 1

            ColumnLayout {
                id: companionActions
                anchors.fill: parent
                anchors.margins: 14
                spacing: 12

                Label {
                    Layout.fillWidth: true
                    text: trx("استخدم هذا القسم فقط على شبكة محلية موثوقة. تشغيل LAN يجعل الهاتف يصل إلى API القراءة فقط مؤقتًا، ورمز الربط قصير العمر ويُستخدم مرة واحدة.", "Use this section only on a trusted local network. LAN mode temporarily lets your phone reach the read-only API; the pairing code is short-lived and single-use.")
                    color: theme.muted
                    wrapMode: Text.Wrap
                }

                CheckBox {
                    id: trustedLanCheck
                    Layout.fillWidth: true
                    checked: card.trustedLanConfirmed
                    text: trx("أؤكد أنني على شبكة محلية موثوقة ولن أشارك QR أو JSON الربط.", "I confirm this is a trusted local network and I will not share the pairing QR or JSON.")
                    onToggled: card.trustedLanConfirmed = checked
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: controller && controller.compactPage ? 1 : 4
                    columnSpacing: 10
                    rowSpacing: 10

                    AppButton {
                        Layout.fillWidth: true
                        text: trx("Generate pairing QR", "Generate pairing QR")
                        role: "success"
                        compact: true
                        enabled: card.trustedLanConfirmed
                        onClicked: card.generateLanPayload()
                    }
                    AppButton {
                        Layout.fillWidth: true
                        text: trx("Start trusted LAN API", "Start trusted LAN API")
                        role: "info"
                        compact: true
                        enabled: card.trustedLanConfirmed
                        onClicked: {
                            var result = backend.startCompanionLanApi(card.trustedLanConfirmed)
                            card.lastResult = result || ({})
                            card.feedbackText = result && result.ok !== false ? trx("تم تشغيل Companion API مؤقتًا للشبكة المحلية الموثوقة.", "Companion API started temporarily for the trusted local network.") : trx("تعذر تشغيل Companion API.", "Could not start Companion API.") + " " + String((result && (result.message || result.user_safe_reason || result.error)) || "")
                        }
                    }
                    AppButton {
                        Layout.fillWidth: true
                        text: trx("Stop API", "Stop API")
                        role: "neutral"
                        compact: true
                        onClicked: {
                            var result = backend.stopCompanionApi()
                            card.lastResult = result || ({})
                            card.feedbackText = trx("تم طلب إيقاف Companion API.", "Companion API stop requested.")
                        }
                    }
                    AppButton {
                        Layout.fillWidth: true
                        text: trx("Revoke devices", "Revoke devices")
                        role: "danger"
                        compact: true
                        onClicked: {
                            var result = backend.revokeAllCompanionDevices()
                            card.lastResult = result || ({})
                            card.feedbackText = result && result.ok !== false ? trx("تم إلغاء ربط جميع الهواتف.", "All companion devices were revoked.") : trx("فشل إلغاء الأجهزة.", "Could not revoke devices.")
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    visible: card.feedbackText.length > 0
                    text: card.feedbackText
                    color: theme.text
                    wrapMode: Text.Wrap
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            visible: card.pairingJson.length > 0
            implicitHeight: pairingJsonColumn.implicitHeight + 28
            radius: 18
            color: theme.surface1
            border.color: theme.border
            border.width: 1

            ColumnLayout {
                id: pairingJsonColumn
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10

                Label {
                    Layout.fillWidth: true
                    text: trx("امسح QR من شاشة Pairing في تطبيق Android. يبقى JSON اليدوي متاحًا كخطة بديلة. الرمز قصير العمر ويُستخدم مرة واحدة.", "Scan this QR with the Android Pairing screen. Manual JSON is kept below as a fallback.")
                    color: theme.muted
                    wrapMode: Text.Wrap
                }


                Rectangle {
                    Layout.alignment: Qt.AlignHCenter
                    visible: card.qrImageDataUri.length > 0
                    width: 260
                    height: 260
                    radius: 22
                    color: "white"
                    border.color: theme.border
                    border.width: 1

                    Image {
                        anchors.centerIn: parent
                        width: 226
                        height: 226
                        source: card.qrImageDataUri
                        fillMode: Image.PreserveAspectFit
                        smooth: false
                    }
                }

                Label {
                    Layout.fillWidth: true
                    visible: card.qrImageDataUri.length > 0
                    text: trx("افتح تطبيق الهاتف > Pair > Scan QR Code ووجّه الكاميرا إلى هذا الرمز.", "Open the phone app > Pair > Scan QR Code and point the camera at this code.")
                    color: theme.text
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                }

                TextArea {
                    id: pairingJsonField
                    Layout.fillWidth: true
                    implicitHeight: 190
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.Wrap
                    text: card.pairingJson
                    color: theme.text
                    background: Rectangle { radius: 14; color: theme.surface2; border.color: theme.border; border.width: 1 }
                }

                AppButton {
                    text: trx("Select all / Copy", "Select all / Copy")
                    role: "info"
                    compact: true
                    onClicked: {
                        pairingJsonField.forceActiveFocus()
                        pairingJsonField.selectAll()
                        pairingJsonField.copy()
                        card.feedbackText = trx("تم نسخ JSON الربط إذا كان clipboard متاحًا؛ وإلا انسخه يدويًا بعد تحديده.", "Pairing JSON copied if clipboard access is available; otherwise copy the selected text manually.")
                    }
                }
            }
        }

        Label {
            Layout.fillWidth: true
            text: trx("تنبيه: الربط يعمل للشبكات المحلية الموثوقة فقط. Health العام لا يعرض حالة النظام، وكل status/live يتطلب token صالح. يتوقف LAN تلقائيًا بعد انتهاء نافذة الربط أو عدم النشاط.", "Warning: Pairing is for trusted local networks only. Public health exposes no system state, and status/live require a valid token. LAN mode auto-stops after the pairing window or inactivity.")
            color: theme.warn
            wrapMode: Text.Wrap
        }
    }
}
