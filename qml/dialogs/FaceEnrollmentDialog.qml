import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme/Ui.js" as Ui

Dialog {
    id: dialog
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property string requestedMode: "enroll"
    property bool enrollmentInFlight: false
    property bool cameraUnavailableRetryAllowed: false
    readonly property bool backendOperationInFlight: backend.faceConfirmationState.faceOperationInFlight === true || backend.faceConfirmationState.operationInFlight === true
    readonly property bool backendConsentGranted: backend.faceConfirmationState.consentGranted === true || backend.faceConfirmationState.faceConsentGranted === true
    readonly property bool cameraUnavailableOnlyEnrollmentBlocker: dialog.cameraUnavailableRetryAllowed && backend.faceConfirmationState.faceEnrollmentFeatureEnabled === true && dialog.backendConsentGranted && backend.faceConfirmationState.canGrantConsent === true && backend.faceConfirmationState.faceModelReady === true && backend.faceConfirmationState.faceEnrollmentUnavailableReason === "camera_unavailable"
    readonly property bool canStartEnrollment: !dialog.enrollmentInFlight && (backend.faceConfirmationState.faceEnrollmentAvailable === true || dialog.cameraUnavailableOnlyEnrollmentBlocker || (!dialog.backendConsentGranted && consentCheck.checked && backend.faceConfirmationState.canGrantConsent === true && backend.faceConfirmationState.faceEnrollmentUnavailableReason === "consent_required"))
    readonly property string backendFaceStatusText: backend.faceConfirmationState.statusText || backend.tr("face_status_not_enrolled")
    readonly property string backendFaceStatusDetail: backend.faceConfirmationState.statusDetail || backend.faceConfirmationState.detailMessage || backend.tr("face_detail_idle")
    readonly property string backendCameraStatusText: backend.faceConfirmationState.cameraStatusText || backend.tr("face_camera_waiting_for_consent")
    readonly property string backendCameraStatusDetail: backend.faceConfirmationState.cameraStatusDetail || backend.tr("face_camera_backend_owned_detail")
    modal: true
    focus: true
    width: Math.min(700, parent ? parent.width - 48 : 700)
    height: Math.min(760, parent ? parent.height - 48 : 760)
    x: parent ? Math.max(24, (parent.width - width) / 2) : 0
    y: parent ? Math.max(24, (parent.height - height) / 2) : 0
    title: backend.tr(requestedMode === "reenroll" ? "face_dialog_reenroll_title" : "face_dialog_enroll_title")

    background: Rectangle {
        radius: 28
        color: Ui.colorToken(theme, "surface0")
        border.color: Ui.colorToken(theme, "border")
        border.width: 1
    }

    function label(arText, enText) {
        return Ui.trx(backend.language === "ar", arText, enText)
    }

    function userSafeFaceText(value, fallbackText) {
        var text = String(value || "")
        if (text.length === 0)
            return fallbackText || ""
        var lower = text.toLowerCase()
        if (lower.indexOf("face") >= 0 && lower.indexOf("model") >= 0 && (lower.indexOf("missing") >= 0 || lower.indexOf("not found") >= 0))
            return dialog.label("تأكيد الوجه يحتاج إلى إعداد", "Face confirmation needs setup")
        if (lower.indexOf("camera") >= 0 && (lower.indexOf("permission") >= 0 || lower.indexOf("unavailable") >= 0))
            return dialog.label("إذن الكاميرا مطلوب", "Camera permission is required")
        if (lower.indexOf("not enrolled") >= 0 || lower.indexOf("not_enrolled") >= 0)
            return dialog.label("تأكيد الوجه يحتاج إلى إعداد", "Face confirmation needs setup")
        if (lower.indexOf("backend") >= 0)
            return dialog.label("تتم المعالجة بأمان من النظام.", "BioAuth is processing this securely.")
        return text
    }

    function openFor(mode, allowCameraUnavailableRetry) {
        requestedMode = mode || "enroll"
        enrollmentInFlight = false
        cameraUnavailableRetryAllowed = allowCameraUnavailableRetry === true
        enrollmentDelayTimer.stop()
        consentCheck.checked = dialog.backendConsentGranted
        open()
    }

    function startEnrollment() {
        if (enrollmentInFlight)
            return
        if (backend.faceConfirmationState.faceEnrollmentAvailable !== true && !dialog.cameraUnavailableOnlyEnrollmentBlocker && !(dialog.canStartEnrollment && consentCheck.checked))
            return
        if (!dialog.canStartEnrollment)
            return
        faceDialogCameraPreview.pauseForBackendCapture()
        if (!dialog.backendConsentGranted && consentCheck.checked && backend.faceConfirmationState.canGrantConsent === true)
            backend.grantFaceTemplateConsent()
        enrollmentInFlight = true
        enrollmentDelayTimer.restart()
    }

    onClosed: {
        enrollmentDelayTimer.stop()
        enrollmentInFlight = false
        faceDialogCameraPreview.pauseForBackendCapture()
    }

    Timer {
        id: enrollmentDelayTimer
        interval: 420
        repeat: false
        onTriggered: {
            backend.prepareFaceBackendCapture()
            backend.enrollFaceTemplate()
        }
    }

    function syncEnrollmentInFlightWithBackend() {
        if (dialog.backendOperationInFlight)
            return
        dialog.enrollmentInFlight = false
        faceDialogCameraPreview.resumeAfterBackendCapture()
    }

    Connections {
        target: backend
        function onFaceConfirmationChanged() { dialog.syncEnrollmentInFlightWithBackend() }
        function onStatusChanged() { dialog.syncEnrollmentInFlightWithBackend() }
    }

    contentItem: ScrollView {
        id: faceDialogScroll
        clip: true
        contentWidth: availableWidth

        ColumnLayout {
            width: faceDialogScroll.availableWidth
            spacing: 14

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: faceDialogHero.implicitHeight + 28
                radius: 22
                color: Ui.colorToken(theme, "surface1")
                border.color: theme.glassBorder || Ui.colorToken(theme, "border")
                border.width: 1

                ColumnLayout {
                    id: faceDialogHero
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 8

                    Label {
                        Layout.fillWidth: true
                        text: backend.tr("face_dialog_body")
                        color: theme.muted
                        font.pixelSize: 14
                        wrapMode: Text.Wrap
                    }

                    CheckBox {
                        id: consentCheck
                        Layout.fillWidth: true
                        text: backend.tr("face_dialog_consent_checkbox")
                        enabled: backend.faceConfirmationState.consentGranted !== true && !dialog.enrollmentInFlight
                        checked: backend.faceConfirmationState.consentGranted === true
                    }
                }
            }

            FaceCameraPreview {
                id: faceDialogCameraPreview
                objectName: "faceDialogCameraPreview"
                Layout.fillWidth: true
                Layout.preferredHeight: 300
                backend: backend
                theme: dialog.theme
                consentGranted: consentCheck.checked || dialog.backendConsentGranted
                previewEnabled: dialog.visible
                backendActionInFlight: dialog.enrollmentInFlight
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: faceDialogStatusColumn.implicitHeight + 24
                radius: 20
                color: Ui.colorToken(theme, "surface1")
                border.color: dialog.backendOperationInFlight || dialog.enrollmentInFlight ? Ui.roleColor(theme, "info") : Ui.colorToken(theme, "border")
                border.width: 1

                ColumnLayout {
                    id: faceDialogStatusColumn
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 8

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        InfoPill {
                            objectName: "faceDialogBackendStatusPill"
                            textValue: dialog.userSafeFaceText(dialog.backendFaceStatusText, backend.tr("face_status_not_enrolled"))
                            pillTone: backend.faceConfirmationState.statusTone || (backend.faceConfirmationState.cameraAvailable ? "neutral" : "warn")
                        }

                        Item { Layout.fillWidth: true }

                        BusyIndicator {
                            running: dialog.enrollmentInFlight || dialog.backendOperationInFlight
                            visible: running
                            Layout.preferredWidth: 26
                            Layout.preferredHeight: 26
                        }
                    }

                    Label {
                        objectName: "faceDialogCameraStatusTitle"
                        Layout.fillWidth: true
                        text: dialog.userSafeFaceText(dialog.backendCameraStatusText, backend.tr("face_camera_waiting_for_consent"))
                        color: theme.text
                        font.pixelSize: 14
                        font.bold: true
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }

                    Label {
                        objectName: "faceDialogCameraStatusBody"
                        Layout.fillWidth: true
                        text: dialog.userSafeFaceText(dialog.backendCameraStatusDetail, backend.tr("face_camera_backend_owned_detail"))
                        color: theme.muted
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                        maximumLineCount: 4
                        elide: Text.ElideRight
                    }

                    Label {
                        objectName: "faceDialogBackendFaceDetail"
                        Layout.fillWidth: true
                        text: dialog.userSafeFaceText(dialog.backendFaceStatusDetail, backend.tr("face_detail_idle"))
                        color: theme.muted
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                        maximumLineCount: 4
                        elide: Text.ElideRight
                    }

                    Label {
                        objectName: "faceDialogCameraRetryHint"
                        Layout.fillWidth: true
                        text: backend.tr("face_enrollment_camera_retry_hint")
                        color: theme.accent
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                        maximumLineCount: 3
                        elide: Text.ElideRight
                        visible: dialog.cameraUnavailableOnlyEnrollmentBlocker
                    }

                    RowLayout {
                        objectName: "faceEnrollmentBusyRow"
                        Layout.fillWidth: true
                        visible: dialog.enrollmentInFlight || dialog.backendOperationInFlight
                        spacing: 8

                        BusyIndicator {
                            objectName: "faceEnrollmentBusyIndicator"
                            running: visible
                            visible: parent.visible
                            Layout.preferredWidth: 28
                            Layout.preferredHeight: 28
                        }

                        Label {
                            Layout.fillWidth: true
                            text: backend.tr("face_capture_in_progress")
                            color: theme.accent
                            font.pixelSize: 13
                            font.bold: true
                            wrapMode: Text.Wrap
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 12

                Item { Layout.fillWidth: true }

                AppButton {
                    Layout.minimumHeight: 44
                    text: backend.tr("cancel")
                    role: "neutral"
                    enabled: !dialog.enrollmentInFlight
                    onClicked: dialog.close()
                }

                AppButton {
                    objectName: "faceStartEnrollmentButton"
                    Layout.minimumHeight: 44
                    text: (dialog.enrollmentInFlight || dialog.backendOperationInFlight) ? backend.tr("face_capture_in_progress") : (dialog.cameraUnavailableOnlyEnrollmentBlocker ? backend.tr("face_retry_with_preview_paused") : backend.tr("face_start_enrollment"))
                    role: "primary"
                    enabled: dialog.canStartEnrollment && !dialog.backendOperationInFlight
                    onClicked: dialog.startEnrollment()
                }
            }
        }
    }
}
