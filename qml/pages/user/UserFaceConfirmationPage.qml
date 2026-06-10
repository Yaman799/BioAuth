import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"
import "../../dialogs"
import "../../theme/Ui.js" as Ui

ScrollView {
    id: root
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property bool faceActionInFlight: false
    property bool facePreviewRequested: false
    property bool showAdvancedFaceControls: false
    property string pendingFaceBackendAction: ""
    readonly property var faceState: backend.faceConfirmationState
    readonly property bool backendOperationInFlight: faceState.faceOperationInFlight === true || faceState.operationInFlight === true
    readonly property int backendFaceCameraIndex: Math.max(0, Math.min(4, Number(faceState.backendFaceCameraIndex === undefined ? 0 : faceState.backendFaceCameraIndex)))
    readonly property bool consentGranted: faceState.faceConsentGranted === true || faceState.consentGranted === true
    readonly property bool faceEnrollmentAvailable: faceState.faceEnrollmentAvailable === true
    readonly property bool faceConfirmationAvailable: faceState.faceConfirmationAvailable === true
    readonly property bool faceEnrollmentFeatureEnabled: faceState.faceEnrollmentFeatureEnabled === true
    readonly property bool faceConfirmationFeatureEnabled: faceState.faceConfirmationFeatureEnabled === true
    readonly property string faceUnavailableReason: faceState.faceConfirmationUnavailableReason || faceState.faceEnrollmentUnavailableReason || "feature_disabled"
    readonly property bool faceEnrollmentCameraUnavailableOnlyBlocker: root.faceEnrollmentFeatureEnabled && root.consentGranted && faceState.canGrantConsent === true && faceState.faceModelReady === true && faceState.faceEnrollmentUnavailableReason === "camera_unavailable"
    readonly property bool canOpenEnrollmentDialog: !root.faceActionInFlight && (root.faceEnrollmentAvailable || root.faceEnrollmentCameraUnavailableOnlyBlocker)
    readonly property bool canEnableFace: faceState.canEnable === true && !faceActionInFlight
    readonly property bool canCheckCamera: faceState.canCheckCamera === true && !faceActionInFlight
    readonly property bool canTestFace: faceState.canTest === true && !faceActionInFlight
    readonly property bool canDeleteFace: faceState.canDelete === true && !faceActionInFlight
    readonly property var latestFaceResult: (faceState && faceState.lastResult) ? faceState.lastResult : ({})
    readonly property string latestFaceResultStatus: String(root.latestFaceResult.operationDisplayStatus || root.latestFaceResult.verificationStatus || root.latestFaceResult.status || faceState.operationStatus || "").toLowerCase()
    readonly property string latestFaceOperationKind: String(root.latestFaceResult.operationKind || faceState.operationKind || "").toLowerCase()
    readonly property bool faceTestInProgress: root.pendingFaceBackendAction === "test" || (root.backendOperationInFlight && root.latestFaceOperationKind === "verification")
    readonly property bool faceTestResultAvailable: root.faceTestInProgress || root.hasFaceResultField("verified") || root.hasFaceResultField("verificationStatus") || root.latestFaceOperationKind === "verification" || root.latestFaceResultStatus === "verified" || root.latestFaceResultStatus === "verified_owner" || root.latestFaceResultStatus === "not_verified" || root.latestFaceResultStatus === "verification_failed"
    readonly property string backendFaceStatusText: faceState.statusText || backend.tr("face_status_not_enrolled")
    readonly property string backendFaceStatusDetail: faceState.statusDetail || faceState.detailMessage || faceState.message || backend.tr("face_detail_idle")
    readonly property string backendCameraStatusText: faceState.cameraStatusText || backend.tr("face_camera_waiting_for_consent")
    readonly property string backendCameraStatusDetail: faceState.cameraStatusDetail || backend.tr("face_camera_backend_owned_detail")
    readonly property string backendEnrollmentStatusText: faceState.faceEnrollmentStatusText || backend.tr("face_status_not_enrolled")
    readonly property string backendEnrollmentStatusDetail: faceState.faceEnrollmentStatusDetail || backend.tr("face_detail_idle")
    readonly property string backendConfirmationStatusText: faceState.faceConfirmationStatusText || backend.tr("face_confirmation_disabled")
    readonly property string backendConfirmationStatusDetail: faceState.faceConfirmationStatusDetail || backend.tr("face_detail_disabled")
    readonly property string backendStatusTone: faceState.statusTone || "neutral"
    readonly property bool compactFaceLayout: root.availableWidth > 0 && root.availableWidth < 920
    readonly property bool narrowFaceLayout: root.availableWidth > 0 && root.availableWidth < 700
    readonly property int pageInset: root.narrowFaceLayout ? 12 : 18
    readonly property int cardInset: root.narrowFaceLayout ? 16 : 20
    readonly property int faceCardRadius: root.narrowFaceLayout ? 22 : 28
    readonly property bool denseFaceLayout: root.availableWidth > 0 && root.availableWidth < 980
    readonly property url heroImage: Qt.resolvedUrl("../../assets/bioauth/01_hero_integrated/04_face_scan_integrated.png")
    readonly property url faceIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/03_face_scan.png")
    readonly property url cameraIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/15_camera.png")
    readonly property url consentIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/11_consent_user_check.png")
    readonly property url qualityIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/16_image_quality.png")
    readonly property url warningIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/19_warning.png")
    readonly property url retryIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/21_retry.png")
    clip: true
    contentWidth: availableWidth

    function label(arText, enText) {
        return Ui.trx(backend.language === "ar", arText, enText)
    }

    function hasFaceResultField(name) {
        return root.latestFaceResult
                && root.latestFaceResult[name] !== undefined
                && root.latestFaceResult[name] !== null
    }

    function normalizedFaceTestStatus() {
        return String(root.latestFaceResultStatus || "").toLowerCase()
    }

    function faceTestVerified() {
        var status = root.normalizedFaceTestStatus()
        return root.latestFaceResult.verified === true || status === "verified" || status === "verified_owner"
    }

    function faceTestResultTone() {
        var status = root.normalizedFaceTestStatus()
        if (root.faceTestInProgress)
            return "info"
        if (root.faceTestVerified())
            return "success"
        if (status === "not_verified")
            return "warn"
        if (status === "camera_unavailable" || status === "no_face_detected" || status === "multiple_faces_detected" || status === "poor_quality" || status === "quality_rejected")
            return "warn"
        if (status === "disabled" || status === "consent_required" || status === "not_enrolled")
            return "warn"
        return "danger"
    }

    function faceTestResultIcon() {
        if (root.faceTestInProgress)
            return "⌁"
        return root.faceTestVerified() ? "✓" : "!"
    }

    function faceTestResultTitle() {
        var status = root.normalizedFaceTestStatus()
        if (root.faceTestInProgress)
            return root.label("جاري فحص الوجه", "Checking face")
        if (root.faceTestVerified())
            return root.label("تم التعرف على الوجه", "Face recognized")
        if (status === "not_verified")
            return root.label("لم يتم التعرف على الوجه", "Face not recognized")
        if (status === "no_face_detected")
            return root.label("لم يظهر وجه بوضوح", "No clear face detected")
        if (status === "multiple_faces_detected")
            return root.label("ظهر أكثر من وجه", "More than one face detected")
        if (status === "poor_quality" || status === "quality_rejected")
            return root.label("الصورة غير واضحة كفاية", "Image is not clear enough")
        if (status === "camera_unavailable")
            return root.label("تعذر استخدام الكاميرا", "Camera could not be used")
        if (status === "consent_required")
            return root.label("الموافقة مطلوبة أولًا", "Consent is required first")
        if (status === "disabled")
            return root.label("تأكيد الوجه غير مفعّل", "Face confirmation is not enabled")
        if (status === "not_enrolled")
            return root.label("إعداد الوجه غير مكتمل", "Face setup is not complete")
        return root.label("لم يكتمل فحص الوجه", "Face check could not finish")
    }

    function faceTestResultDetail() {
        var status = root.normalizedFaceTestStatus()
        if (root.faceTestInProgress)
            return root.label("ابقَ أمام الكاميرا للحظات. سيظهر هنا ملخص النتيجة بعد انتهاء الفحص.", "Stay in front of the camera for a moment. The result will appear here when the check finishes.")
        if (root.faceTestVerified())
            return root.label("الوجه الحالي يطابق التسجيل المحفوظ لهذا الحساب.", "The current face matches the saved setup for this account.")
        if (status === "not_verified")
            return root.label("الوجه الحالي لا يطابق التسجيل المحفوظ. تأكد من الإضاءة وقربك من الكاميرا ثم جرّب مرة أخرى.", "The current face does not match the saved setup. Check lighting, stay close to the camera, and try again.")
        if (status === "no_face_detected")
            return root.label("اجلس أمام الكاميرا بوضوح ثم أعد الفحص.", "Sit clearly in front of the camera, then run the check again.")
        if (status === "multiple_faces_detected")
            return root.label("يفضل أن يظهر شخص واحد فقط أمام الكاميرا أثناء الفحص.", "Only one person should be visible during the check.")
        if (status === "poor_quality" || status === "quality_rejected")
            return root.label("حسّن الإضاءة وثبّت وجهك أمام الكاميرا ثم حاول مرة أخرى.", "Improve lighting, keep your face steady, and try again.")
        if (status === "camera_unavailable")
            return root.label("تأكد أن الكاميرا متصلة وغير مستخدمة من تطبيق آخر.", "Make sure the camera is connected and not being used by another app.")
        if (status === "consent_required")
            return root.label("امنح موافقة استخدام الكاميرا وإعداد الوجه قبل تشغيل الفحص.", "Grant camera and face setup consent before running the check.")
        if (status === "disabled")
            return root.label("فعّل تأكيد الوجه أولًا، ثم اضغط اختبار الوجه.", "Enable face confirmation first, then run the face test.")
        if (status === "not_enrolled")
            return root.label("أكمل إعداد بصمة الوجه حتى يستطيع BioAuth مقارنة الوجه الحالي.", "Complete face setup so BioAuth can compare the current face.")
        return root.userSafeFaceText(root.backendConfirmationStatusDetail, root.label("جرّب الفحص مرة أخرى بعد التأكد من الكاميرا والإضاءة.", "Try again after checking the camera and lighting."))
    }

    function tourTarget(name) {
        if (name === "faceHero") return faceHeroCard
        return null
    }

    function isAttentionTone(tone) {
        var t = String(tone || "").toLowerCase()
        return t === "warn" || t === "warning" || t === "danger" || t === "error"
    }

    function userSafeFaceText(value, fallbackText) {
        var text = String(value || "")
        if (text.length === 0)
            return fallbackText || ""
        var lower = text.toLowerCase()
        if (lower.indexOf("face") >= 0 && lower.indexOf("model") >= 0 && (lower.indexOf("missing") >= 0 || lower.indexOf("not found") >= 0))
            return root.label("تأكيد الوجه يحتاج إلى إعداد", "Face confirmation needs setup")
        if (lower.indexOf("model") >= 0 && lower.indexOf("file") >= 0 && lower.indexOf("missing") >= 0)
            return root.label("إعداد الوجه غير مكتمل", "Face setup is incomplete")
        if (lower.indexOf("camera") >= 0 && (lower.indexOf("permission") >= 0 || lower.indexOf("unavailable") >= 0))
            return root.label("إذن الكاميرا مطلوب", "Camera permission is required")
        if (lower.indexOf("not enrolled") >= 0 || lower.indexOf("not_enrolled") >= 0)
            return root.label("تأكيد الوجه يحتاج إلى إعداد", "Face confirmation needs setup")
        if (lower.indexOf("consent") >= 0 && lower.indexOf("required") >= 0)
            return root.label("الموافقة مطلوبة قبل إعداد الوجه", "Consent is required before face setup")
        if (lower.indexOf("backend") >= 0)
            return root.label("تتم المعالجة بأمان من النظام.", "BioAuth is processing this securely.")
        return text
    }

    function conciseFaceSummary() {
        if (root.faceActionInFlight || root.backendOperationInFlight)
            return backend.tr("user_action_in_progress")
        if (root.isAttentionTone(root.backendStatusTone))
            return root.label("يحتاج انتباهًا", "Needs attention")
        if (root.faceState.enrolled === true)
            return root.label("اكتمل التسجيل", "Enrollment completed")
        if (!root.consentGranted)
            return root.label("الموافقة مطلوبة", "Consent required")
        if (root.faceConfirmationAvailable)
            return root.label("جاهز للتأكيد", "Ready for confirmation")
        return root.userSafeFaceText(root.backendFaceStatusText, root.label("تأكيد الوجه يحتاج إلى إعداد", "Face confirmation needs setup"))
    }

    function conciseCameraSummary() {
        var status = String(root.faceState.cameraStatus || root.faceState.faceCameraStatus || "not_checked").toLowerCase()
        if (status === "checking_camera")
            return root.label("جارٍ فحص الكاميرا", "Checking camera")
        if (root.faceState.cameraAvailable === true)
            return root.label("الكاميرا متاحة", "Camera available")
        if (status === "not_checked" || status === "waiting_for_consent")
            return root.label("لم يتم فحص الكاميرا", "Camera not checked")
        if (root.consentGranted)
            return root.label("إذن الكاميرا مطلوب", "Camera permission is required")
        return root.label("الموافقة أولاً", "Consent first")
    }

    Timer {
        id: faceGuardTimer
        interval: 15000
        repeat: false
        onTriggered: {
            if (!root.backendOperationInFlight) {
                root.faceActionInFlight = false
                root.pendingFaceBackendAction = ""
                pageFacePreview.resumeAfterBackendCapture()
            }
        }
    }


    function syncFaceActionWithBackend() {
        if (root.backendOperationInFlight)
            return
        root.faceActionInFlight = false
        backendCaptureDelayTimer.stop()
        root.pendingFaceBackendAction = ""
        pageFacePreview.resumeAfterBackendCapture()
    }

    Connections {
        target: backend
        function onFaceConfirmationChanged() { root.syncFaceActionWithBackend() }
        function onStatusChanged() { root.syncFaceActionWithBackend() }
    }

    function openEnrollmentDialog(reenroll) {
        if (!root.canOpenEnrollmentDialog)
            return
        if (!root.consentGranted && !root.faceState.canGrantConsent)
            return
        root.facePreviewRequested = false
        pageFacePreview.pauseForBackendCapture()
        faceDialog.openFor(reenroll ? "reenroll" : "enroll", root.faceEnrollmentCameraUnavailableOnlyBlocker)
    }

    function guardedToggleFace(enabled) {
        if (root.faceActionInFlight)
            return
        root.faceActionInFlight = true
        faceGuardTimer.restart()
        backend.setFaceConfirmationEnabled(enabled)
    }

    function guardedToggleFaceEnrollmentFeature(enabled) {
        if (root.faceActionInFlight)
            return
        root.faceActionInFlight = true
        faceGuardTimer.restart()
        backend.setFaceEnrollmentFeatureEnabled(enabled)
    }

    function guardedToggleFaceConfirmationFeature(enabled) {
        if (root.faceActionInFlight)
            return
        root.faceActionInFlight = true
        faceGuardTimer.restart()
        backend.setFaceConfirmationFeatureEnabled(enabled)
    }

    function guardedTestFace() {
        if (!root.canTestFace)
            return
        root.runBackendAfterPreviewPause("test")
    }

    function guardedDeleteTemplate() {
        if (!root.canDeleteFace)
            return
        faceDeleteTemplateDialog.open()
    }

    function performDeleteTemplate() {
        if (!root.canDeleteFace)
            return
        root.faceActionInFlight = true
        faceGuardTimer.restart()
        backend.deleteFaceTemplate()
    }

    function guardedRefreshFaceState() {
        if (root.faceActionInFlight)
            return
        root.runBackendAfterPreviewPause("refresh")
    }

    function guardedCheckCamera() {
        if (!root.canCheckCamera)
            return
        root.runBackendAfterPreviewPause("checkCamera")
    }

    function runBackendAfterPreviewPause(actionName) {
        pageFacePreview.pauseForBackendCapture()
        root.faceActionInFlight = true
        root.pendingFaceBackendAction = actionName
        faceGuardTimer.restart()
        backendCaptureDelayTimer.restart()
    }

    function saveBackendCameraIndex(index) {
        if (root.faceActionInFlight)
            return
        pageFacePreview.pauseForBackendCapture()
        root.faceActionInFlight = true
        faceGuardTimer.restart()
        backend.setBackendFaceCameraIndex(index)
    }

    Timer {
        id: backendCaptureDelayTimer
        interval: 420
        repeat: false
        onTriggered: {
            if (root.pendingFaceBackendAction === "test")
                backend.testFaceConfirmation()
            else if (root.pendingFaceBackendAction === "checkCamera")
                backend.requestFaceCameraCheck()
            else if (root.pendingFaceBackendAction === "refresh")
                backend.refreshFaceConfirmationState()
            root.pendingFaceBackendAction = ""
        }
    }

    function toggleDisplayOnlyPreview() {
        if (root.faceActionInFlight)
            return
        root.facePreviewRequested = !root.facePreviewRequested
        if (!root.facePreviewRequested)
            pageFacePreview.pauseForBackendCapture()
        else
            pageFacePreview.resumeAfterBackendCapture()
    }

    FaceEnrollmentDialog {
        id: faceDialog
        rootWindow: root
    }

    ConfirmDialog {
        id: faceDeleteTemplateDialog
        rootWindow: root.rootWindow ? root.rootWindow : root
        bodyText: root.label("حذف قالب الوجه سيوقف استخدام تأكيد الوجه إلى أن تقوم بالتسجيل من جديد. هل تريد المتابعة؟", "Deleting the face template stops face confirmation until you enroll again. Continue?")
        confirmText: root.label("حذف قالب الوجه", "Delete face template")
        cancelText: root.label("إلغاء", "Cancel")
        tone: "danger"
        onConfirmed: root.performDeleteTemplate()
    }

    ColumnLayout {
        width: root.availableWidth
        spacing: root.narrowFaceLayout ? 14 : 18

        GlassCard {
            id: faceHeroCard
            Layout.fillWidth: true
            implicitHeight: Math.max(root.denseFaceLayout ? 520 : 410, faceHeroRow.implicitHeight + (root.denseFaceLayout ? 32 : 44))
            Layout.minimumHeight: implicitHeight

            RowLayout {
                id: faceHeroRow
                anchors.fill: parent
                anchors.margins: root.denseFaceLayout ? 16 : 22
                spacing: root.denseFaceLayout ? 14 : 22

                ColumnLayout {
                    id: faceHeroContent
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: root.denseFaceLayout ? faceHeroCard.width : faceHeroCard.width * 0.60
                    Layout.maximumWidth: root.denseFaceLayout ? faceHeroCard.width : faceHeroCard.width * 0.62
                    spacing: 14

                    Flow {
                        id: statusPillFlow
                        Layout.fillWidth: true
                        Layout.preferredHeight: implicitHeight
                        spacing: 8

                        InfoPill {
                            objectName: "faceBackendStatusPill"
                            textValue: root.conciseFaceSummary()
                            pillTone: root.backendStatusTone
                        }

                        InfoPill {
                            objectName: "faceBackendCameraStatusPill"
                            textValue: root.conciseCameraSummary()
                            pillTone: root.faceState.cameraAvailable ? "neutral" : "warn"
                        }

                        InfoPill {
                            objectName: "faceBackendEnabledPill"
                            textValue: root.faceState.enabled ? backend.tr("enabled") : backend.tr("disabled")
                            pillTone: root.faceState.enabled ? "success" : "neutral"
                        }

                        InfoPill {
                            textValue: root.consentGranted ? backend.tr("face_consent_recorded") : backend.tr("face_consent_needed")
                            pillTone: root.consentGranted ? "success" : "warn"
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        AssetIcon {
                            sourceUrl: root.faceIcon
                            tone: root.backendStatusTone
                            Layout.preferredWidth: 44
                            Layout.preferredHeight: 44
                            iconPadding: 7
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4

                            Label {
                                Layout.fillWidth: true
                                text: backend.tr("face_page_title")
                                color: theme.text
                                font.pixelSize: root.narrowFaceLayout ? 26 : 34
                                font.bold: true
                                wrapMode: Text.Wrap
                            }

                            Label {
                                Layout.fillWidth: true
                                text: backend.tr("face_page_subtitle")
                                color: theme.muted
                                font.pixelSize: root.narrowFaceLayout ? 14 : 15
                                lineHeight: 1.08
                                wrapMode: Text.Wrap
                                maximumLineCount: root.narrowFaceLayout ? 5 : 3
                                elide: Text.ElideRight
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: faceHeroStatusRow.implicitHeight + 24
                        radius: 20
                        color: Ui.colorToken(theme, "surface2")
                        border.color: root.faceActionInFlight ? Ui.roleColor(theme, "info") : Ui.colorToken(theme, "border")
                        border.width: 1

                        RowLayout {
                            id: faceHeroStatusRow
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 12

                            AssetIcon {
                                sourceUrl: root.faceActionInFlight || root.backendOperationInFlight ? root.retryIcon : root.consentIcon
                                tone: root.faceActionInFlight || root.backendOperationInFlight ? "info" : root.backendStatusTone
                                Layout.preferredWidth: 38
                                Layout.preferredHeight: 38
                                iconPadding: 7
                            }

                            BusyIndicator {
                                running: root.faceActionInFlight || root.backendOperationInFlight
                                visible: running
                                Layout.preferredWidth: 24
                                Layout.preferredHeight: 24
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3

                                Label {
                                    objectName: "faceBackendStatusMessage"
                                    Layout.fillWidth: true
                                    text: root.faceActionInFlight ? backend.tr("user_action_in_progress") : root.conciseFaceSummary()
                                    color: root.faceActionInFlight ? Ui.roleColor(theme, "info") : theme.text
                                    font.pixelSize: 15
                                    font.bold: true
                                    wrapMode: Text.Wrap
                                    maximumLineCount: 2
                                    elide: Text.ElideRight
                                }

                                Label {
                                    objectName: "faceBackendStatusDetail"
                                    Layout.fillWidth: true
                                    text: root.backendFaceStatusDetail
                                    color: theme.muted
                                    font.pixelSize: 13
                                    wrapMode: Text.Wrap
                                    maximumLineCount: 4
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }

                HeroAssetFrame {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: faceHeroCard.width * 0.38
                    visible: !root.denseFaceLayout
                    sourceUrl: root.heroImage
                    tone: root.backendStatusTone
                    cornerRadius: 26
                    imageBleed: 8
                    imageFillMode: Image.PreserveAspectCrop
                    imageOpacity: 1.0
                    overlayOpacity: 0.0
                    edgeFadeOpacity: 0.0
                    ambientWashOpacity: 0.0
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: root.compactFaceLayout ? 1 : 2
            rowSpacing: root.narrowFaceLayout ? 14 : 18
            columnSpacing: root.narrowFaceLayout ? 14 : 18

            GlassCard {
                Layout.fillWidth: true
                Layout.preferredWidth: root.compactFaceLayout ? root.availableWidth : 620
                implicitHeight: facePreviewCardColumn.implicitHeight + (root.cardInset * 2)

                ColumnLayout {
                    id: facePreviewCardColumn
                    anchors.fill: parent
                    anchors.margins: root.cardInset
                    spacing: 14

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 4

                            Label {
                                Layout.fillWidth: true
                                text: backend.tr("face_preview_title")
                                color: theme.text
                                font.pixelSize: root.narrowFaceLayout ? 19 : 21
                                font.bold: true
                                wrapMode: Text.Wrap
                            }

                            Label {
                                Layout.fillWidth: true
                                text: backend.tr("face_preview_body")
                                color: theme.muted
                                font.pixelSize: 13
                                wrapMode: Text.Wrap
                                maximumLineCount: root.narrowFaceLayout ? 5 : 3
                                elide: Text.ElideRight
                            }
                        }

                        AppButton {
                            objectName: "faceTogglePreviewButton"
                            text: root.facePreviewRequested ? backend.tr("face_preview_hide") : backend.tr("face_preview_show")
                            role: "details"
                            compact: true
                            enabled: !root.faceActionInFlight
                            onClicked: root.toggleDisplayOnlyPreview()
                        }
                    }

                    FaceCameraPreview {
                        id: pageFacePreview
                        objectName: "facePageCameraPreview"
                        Layout.fillWidth: true
                        Layout.preferredHeight: root.narrowFaceLayout ? 260 : 330
                        backend: backend
                        theme: root.theme
                        consentGranted: root.consentGranted
                        previewEnabled: root.facePreviewRequested
                        backendActionInFlight: root.faceActionInFlight
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: faceCameraDetailColumn.implicitHeight + 20
                        radius: 18
                        color: theme.surface1
                        border.color: root.faceState.cameraAvailable ? (theme.glassBorder || theme.border) : theme.warn
                        border.width: 1

                        ColumnLayout {
                            id: faceCameraDetailColumn
                            anchors.fill: parent
                            anchors.margins: 10
                            spacing: 4

                            Label {
                                objectName: "faceBackendCameraDetail"
                                Layout.fillWidth: true
                                text: root.backendCameraStatusDetail
                                color: theme.muted
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                                maximumLineCount: 4
                                elide: Text.ElideRight
                            }

                            Label {
                                Layout.fillWidth: true
                                text: backend.tr("face_camera_preview_body")
                                color: theme.muted
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                                maximumLineCount: 3
                                elide: Text.ElideRight
                            }
                        }
                    }
                }
            }

            GlassCard {
                Layout.fillWidth: true
                Layout.preferredWidth: root.compactFaceLayout ? root.availableWidth : 420
                implicitHeight: faceStatusColumn.implicitHeight + (root.cardInset * 2)

                ColumnLayout {
                    id: faceStatusColumn
                    anchors.fill: parent
                    anchors.margins: root.cardInset
                    spacing: 14

                    Label {
                        Layout.fillWidth: true
                        text: backend.tr("face_page_status_title")
                        color: theme.text
                        font.pixelSize: root.narrowFaceLayout ? 19 : 21
                        font.bold: true
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: backend.tr("face_page_status_body")
                        color: theme.muted
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: faceStatusMessageColumn.implicitHeight + 24
                        radius: 18
                        color: theme.surface1
                        border.color: theme.border
                        border.width: 1

                        ColumnLayout {
                            id: faceStatusMessageColumn
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 6

                            Label {
                                Layout.fillWidth: true
                                text: root.conciseFaceSummary()
                                color: theme.text
                                font.pixelSize: 14
                                font.bold: true
                                wrapMode: Text.Wrap
                            }

                            Label {
                                Layout.fillWidth: true
                                text: root.userSafeFaceText(root.backendFaceStatusDetail, backend.tr("face_detail_idle"))
                                color: theme.muted
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                                maximumLineCount: 4
                                elide: Text.ElideRight
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: faceCameraStatusColumn.implicitHeight + 24
                        radius: 18
                        color: theme.surface1
                        border.color: root.faceState.cameraAvailable ? (theme.glassBorder || theme.border) : theme.warn
                        border.width: 1

                        ColumnLayout {
                            id: faceCameraStatusColumn
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 6

                            Label {
                                Layout.fillWidth: true
                                text: root.conciseCameraSummary()
                                color: theme.text
                                font.pixelSize: 14
                                font.bold: true
                                wrapMode: Text.Wrap
                            }

                            Label {
                                Layout.fillWidth: true
                                text: root.userSafeFaceText(root.backendCameraStatusDetail, backend.tr("face_camera_backend_owned_detail"))
                                color: theme.muted
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                                maximumLineCount: 4
                                elide: Text.ElideRight
                            }
                        }
                    }

                    RowLayout {
                        objectName: "facePageBusyRow"
                        Layout.fillWidth: true
                        visible: root.faceActionInFlight || root.backendOperationInFlight
                        spacing: 8

                        BusyIndicator {
                            objectName: "facePageBusyIndicator"
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

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        AppButton {
                            objectName: "faceCheckCameraButton"
                            Layout.fillWidth: true
                            text: backend.tr("face_check_camera")
                            role: "primary"
                            enabled: root.canCheckCamera
                            onClicked: root.guardedCheckCamera()
                        }

                        AppButton {
                            objectName: "faceRefreshStatusButton"
                            Layout.fillWidth: true
                            text: backend.tr("face_refresh_status")
                            role: "details"
                            enabled: !root.faceActionInFlight
                            onClicked: root.guardedRefreshFaceState()
                        }
                    }
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: root.compactFaceLayout ? 1 : 2
            rowSpacing: root.narrowFaceLayout ? 14 : 18
            columnSpacing: root.narrowFaceLayout ? 14 : 18

            GlassCard {
                Layout.fillWidth: true
                implicitHeight: faceEnrollmentColumn.implicitHeight + (root.cardInset * 2)

                ColumnLayout {
                    id: faceEnrollmentColumn
                    anchors.fill: parent
                    anchors.margins: root.cardInset
                    spacing: 14

                    Label {
                        Layout.fillWidth: true
                        text: root.consentGranted ? backend.tr("face_page_consent_recorded_title") : backend.tr("face_page_consent_title")
                        color: theme.text
                        font.pixelSize: root.narrowFaceLayout ? 19 : 21
                        font.bold: true
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.consentGranted ? backend.tr("face_page_consent_recorded_body") : backend.tr("face_page_consent_body")
                        color: theme.muted
                        font.pixelSize: 14
                        wrapMode: Text.Wrap
                    }

                    InfoPill {
                        textValue: root.consentGranted ? backend.tr("face_consent_recorded") : backend.tr("face_consent_needed")
                        pillTone: root.consentGranted ? "success" : "warn"
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: faceEnrollmentReadinessColumn.implicitHeight + 22
                        radius: 18
                        color: theme.surface1
                        border.color: root.faceEnrollmentAvailable ? (theme.glassBorder || theme.border) : theme.border
                        border.width: 1

                        ColumnLayout {
                            id: faceEnrollmentReadinessColumn
                            anchors.fill: parent
                            anchors.margins: 11
                            spacing: 5

                            Label {
                                objectName: "faceEnrollmentReadinessText"
                                Layout.fillWidth: true
                                text: backend.tr("face_enrollment_readiness_prefix") + " " + root.userSafeFaceText(root.backendEnrollmentStatusText, root.label("تأكيد الوجه يحتاج إلى إعداد", "Face confirmation needs setup"))
                                color: root.faceEnrollmentAvailable ? theme.success : theme.text
                                font.pixelSize: 13
                                font.bold: true
                                wrapMode: Text.Wrap
                            }

                            Label {
                                objectName: "faceEnrollmentReadinessDetail"
                                Layout.fillWidth: true
                                text: root.userSafeFaceText(root.backendEnrollmentStatusDetail, backend.tr("face_detail_idle"))
                                color: theme.muted
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                                maximumLineCount: 4
                                elide: Text.ElideRight
                            }

                            Label {
                                objectName: "faceEnrollmentActionHint"
                                Layout.fillWidth: true
                                text: root.faceEnrollmentCameraUnavailableOnlyBlocker ? backend.tr("face_enrollment_camera_retry_hint") : backend.tr("face_enrollment_disabled_reason_hint")
                                color: root.faceEnrollmentCameraUnavailableOnlyBlocker ? theme.accent : theme.muted
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                                maximumLineCount: 3
                                elide: Text.ElideRight
                                visible: !root.faceEnrollmentAvailable
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        AppButton {
                            Layout.fillWidth: true
                            Layout.minimumHeight: 44
                            text: root.consentGranted ? backend.tr("face_consent_recorded") : backend.tr("face_grant_consent")
                            role: "primary"
                            enabled: !root.faceActionInFlight && !root.consentGranted && root.faceState.canGrantConsent
                            onClicked: {
                                if (root.faceActionInFlight || root.consentGranted || !root.faceState.canGrantConsent)
                                    return
                                root.faceActionInFlight = true
                                faceGuardTimer.restart()
                                backend.grantFaceTemplateConsent()
                            }
                        }

                        AppButton {
                            Layout.fillWidth: true
                            Layout.minimumHeight: 44
                            text: root.faceEnrollmentCameraUnavailableOnlyBlocker ? backend.tr("face_prepare_enrollment") : backend.tr("face_open_enrollment")
                            role: "details"
                            enabled: root.canOpenEnrollmentDialog
                            onClicked: root.openEnrollmentDialog(false)
                        }
                    }
                }
            }

            GlassCard {
                Layout.fillWidth: true
                implicitHeight: faceControlsColumn.implicitHeight + (root.cardInset * 2)

                ColumnLayout {
                    id: faceControlsColumn
                    anchors.fill: parent
                    anchors.margins: root.cardInset
                    spacing: 14

                    Label {
                        Layout.fillWidth: true
                        text: backend.tr("face_page_controls_title")
                        color: theme.text
                        font.pixelSize: root.narrowFaceLayout ? 19 : 21
                        font.bold: true
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: backend.tr("face_page_controls_body")
                        color: theme.muted
                        font.pixelSize: 14
                        wrapMode: Text.Wrap
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: faceConfirmationReadinessColumn.implicitHeight + 22
                        radius: 18
                        color: theme.surface1
                        border.color: root.faceConfirmationAvailable ? (theme.glassBorder || theme.border) : theme.border
                        border.width: 1

                        ColumnLayout {
                            id: faceConfirmationReadinessColumn
                            anchors.fill: parent
                            anchors.margins: 11
                            spacing: 5

                            Label {
                                objectName: "faceConfirmationReadinessText"
                                Layout.fillWidth: true
                                text: backend.tr("face_confirmation_readiness_prefix") + " " + root.userSafeFaceText(root.backendConfirmationStatusText, root.label("تأكيد الوجه يحتاج إلى إعداد", "Face confirmation needs setup"))
                                color: root.faceConfirmationAvailable ? theme.success : theme.text
                                font.pixelSize: 13
                                font.bold: true
                                wrapMode: Text.Wrap
                            }

                            Label {
                                objectName: "faceConfirmationReadinessDetail"
                                Layout.fillWidth: true
                                text: root.userSafeFaceText(root.backendConfirmationStatusDetail, backend.tr("face_detail_disabled"))
                                color: theme.muted
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                                maximumLineCount: 4
                                elide: Text.ElideRight
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        AppButton {
                            Layout.fillWidth: true
                            Layout.minimumHeight: 44
                            text: backend.tr("face_enable_confirmation")
                            role: "primary"
                            enabled: root.canEnableFace && !root.faceState.enabled
                            onClicked: root.guardedToggleFace(true)
                        }

                        AppButton {
                            Layout.fillWidth: true
                            Layout.minimumHeight: 44
                            text: backend.tr("face_disable_confirmation")
                            role: "neutral"
                            enabled: root.faceState.enabled && !root.faceActionInFlight
                            onClicked: root.guardedToggleFace(false)
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        AppButton {
                            objectName: "faceTestConfirmationButton"
                            Layout.fillWidth: true
                            Layout.minimumHeight: 44
                            text: backend.tr("face_test_confirmation")
                            role: "details"
                            enabled: root.canTestFace
                            onClicked: root.guardedTestFace()
                        }

                        AppButton {
                            objectName: "faceReenrollButton"
                            Layout.fillWidth: true
                            Layout.minimumHeight: 44
                            text: root.faceEnrollmentCameraUnavailableOnlyBlocker ? backend.tr("face_prepare_reenrollment") : backend.tr("face_reenroll")
                            role: "details"
                            enabled: root.canOpenEnrollmentDialog
                            onClicked: root.openEnrollmentDialog(true)
                        }

                        AppButton {
                            objectName: "faceDeleteTemplateButton"
                            Layout.fillWidth: true
                            Layout.minimumHeight: 44
                            text: backend.tr("face_delete_template")
                            role: "danger"
                            enabled: root.canDeleteFace
                            onClicked: root.guardedDeleteTemplate()
                        }
                    }

                    Rectangle {
                        id: faceTestResultPanel
                        objectName: "faceTestResultPanel"
                        Layout.fillWidth: true
                        implicitHeight: faceTestResultLayout.implicitHeight + 24
                        visible: root.faceTestResultAvailable
                        radius: 18
                        color: {
                            var c = Ui.roleColor(theme, root.faceTestResultTone())
                            return Qt.rgba(c.r, c.g, c.b, theme.isDark ? 0.13 : 0.09)
                        }
                        border.color: {
                            var c = Ui.roleColor(theme, root.faceTestResultTone())
                            return Qt.rgba(c.r, c.g, c.b, theme.isDark ? 0.44 : 0.32)
                        }
                        border.width: 1

                        Behavior on opacity {
                            NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
                        }

                        RowLayout {
                            id: faceTestResultLayout
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 12

                            Rectangle {
                                Layout.alignment: Qt.AlignTop
                                Layout.preferredWidth: 42
                                Layout.preferredHeight: 42
                                radius: 21
                                color: {
                                    var c = Ui.roleColor(theme, root.faceTestResultTone())
                                    return Qt.rgba(c.r, c.g, c.b, theme.isDark ? 0.22 : 0.16)
                                }
                                border.color: {
                                    var c = Ui.roleColor(theme, root.faceTestResultTone())
                                    return Qt.rgba(c.r, c.g, c.b, theme.isDark ? 0.62 : 0.42)
                                }

                                Label {
                                    anchors.centerIn: parent
                                    text: root.faceTestResultIcon()
                                    color: theme.text
                                    font.pixelSize: root.faceTestInProgress ? 22 : 24
                                    font.bold: true
                                }

                                RotationAnimator on rotation {
                                    running: root.faceTestInProgress && faceTestResultPanel.visible
                                    from: 0
                                    to: 360
                                    duration: 1200
                                    loops: Animation.Infinite
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
                                        text: root.faceTestResultTitle()
                                        color: theme.text
                                        font.pixelSize: 14
                                        font.bold: true
                                        wrapMode: Text.Wrap
                                    }

                                    InfoPill {
                                        visible: !root.narrowFaceLayout
                                        theme: root.theme
                                        pillTone: root.faceTestResultTone()
                                        textValue: root.faceTestInProgress
                                                   ? root.label("قيد الفحص", "Checking")
                                                   : root.label("نتيجة الفحص", "Check result")
                                    }
                                }

                                Label {
                                    Layout.fillWidth: true
                                    text: root.faceTestResultDetail()
                                    color: theme.muted
                                    font.pixelSize: 12
                                    lineHeight: 1.16
                                    wrapMode: Text.Wrap
                                    maximumLineCount: 5
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }
            }
        }

        GlassCard {
            Layout.fillWidth: true
            implicitHeight: faceSettingsColumn.implicitHeight + (root.cardInset * 2)

            ColumnLayout {
                id: faceSettingsColumn
                anchors.fill: parent
                anchors.margins: root.cardInset
                spacing: 14

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12

                    AssetIcon {
                        sourceUrl: root.warningIcon
                        tone: root.showAdvancedFaceControls ? "warn" : "neutral"
                        Layout.preferredWidth: 42
                        Layout.preferredHeight: 42
                        iconPadding: 7
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4

                        Label {
                            Layout.fillWidth: true
                            text: root.label("خيارات الوجه المتقدمة", "Advanced face options")
                            color: theme.text
                            font.pixelSize: root.narrowFaceLayout ? 19 : 21
                            font.bold: true
                            wrapMode: Text.Wrap
                        }

                        Label {
                            Layout.fillWidth: true
                            text: root.label("إعداد الوجه اليومي موجود في البطاقات أعلاه. افتح هذه الخيارات فقط عند تغيير الكاميرا أو تعطيل ميزة بأمر واضح.", "Daily face setup stays in the cards above. Open these options only to change the camera or intentionally disable a feature.")
                            color: theme.muted
                            font.pixelSize: 14
                            wrapMode: Text.Wrap
                        }
                    }

                    AppButton {
                        text: root.showAdvancedFaceControls ? root.label("إخفاء", "Hide") : root.label("عرض", "Show")
                        role: root.showAdvancedFaceControls ? "warn" : "neutral"
                        compact: true
                        enabled: !root.faceActionInFlight
                        onClicked: root.showAdvancedFaceControls = !root.showAdvancedFaceControls
                    }
                }

                StatusInfoRow {
                    Layout.fillWidth: true
                    iconSource: root.cameraIcon
                    tone: root.showAdvancedFaceControls ? "warn" : "neutral"
                    title: root.label("الوضع الافتراضي آمن", "Safe default")
                    detail: root.label("لا تحتاج لتغيير رقم الكاميرا أو مفاتيح الميزات للاستخدام اليومي.", "You do not need to change the camera index or feature switches for daily use.")
                }

                GridLayout {
                    visible: root.showAdvancedFaceControls
                    enabled: visible
                    Layout.preferredHeight: visible ? implicitHeight : 0
                    Layout.minimumHeight: visible ? implicitHeight : 0
                    Layout.maximumHeight: visible ? 1000000 : 0
                    Layout.fillWidth: true
                    columns: root.compactFaceLayout ? 1 : 3
                    columnSpacing: 12
                    rowSpacing: 12

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: backendCameraIndexRow.implicitHeight + 24
                        radius: 18
                        color: theme.surface1
                        border.color: theme.border
                        border.width: 1

                        RowLayout {
                            id: backendCameraIndexRow
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 12

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Label { text: backend.tr("face_backend_camera_index_title"); color: theme.text; font.bold: true; wrapMode: Text.Wrap }
                                Label { text: backend.tr("face_backend_camera_index_body"); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: 12 }
                            }

                            ComboBox {
                                objectName: "faceBackendCameraIndexSelector"
                                model: [0, 1, 2, 3, 4]
                                currentIndex: root.backendFaceCameraIndex
                                enabled: !root.faceActionInFlight
                                Layout.preferredWidth: 96
                                onActivated: function(index) { root.saveBackendCameraIndex(model[index]) }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: faceEnrollmentFeatureRow.implicitHeight + 24
                        radius: 18
                        color: theme.surface1
                        border.color: root.faceEnrollmentFeatureEnabled ? (theme.glassBorder || theme.border) : theme.border
                        border.width: 1

                        RowLayout {
                            id: faceEnrollmentFeatureRow
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 12

                            StartupSwitch {
                                objectName: "faceEnrollmentFeatureToggle"
                                checked: root.faceEnrollmentFeatureEnabled
                                enabled: !root.faceActionInFlight
                                onToggled: function(nextChecked) { root.guardedToggleFaceEnrollmentFeature(nextChecked) }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Label { text: backend.tr("face_enable_enrollment_setting"); color: theme.text; font.bold: true; wrapMode: Text.Wrap }
                                Label { text: root.faceEnrollmentFeatureEnabled ? backend.tr("face_enrollment_feature_enabled") : backend.tr("face_enrollment_feature_disabled"); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: 12 }
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: faceConfirmationFeatureRow.implicitHeight + 24
                        radius: 18
                        color: theme.surface1
                        border.color: root.faceConfirmationFeatureEnabled ? (theme.glassBorder || theme.border) : theme.border
                        border.width: 1

                        RowLayout {
                            id: faceConfirmationFeatureRow
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 12

                            StartupSwitch {
                                objectName: "faceConfirmationFeatureToggle"
                                checked: root.faceConfirmationFeatureEnabled
                                enabled: !root.faceActionInFlight
                                onToggled: function(nextChecked) { root.guardedToggleFaceConfirmationFeature(nextChecked) }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 4
                                Label { text: backend.tr("face_enable_confirmation_setting"); color: theme.text; font.bold: true; wrapMode: Text.Wrap }
                                Label { text: root.faceConfirmationFeatureEnabled ? backend.tr("face_confirmation_feature_enabled") : backend.tr("face_confirmation_feature_disabled"); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: 12 }
                            }
                        }
                    }
                }
            }
        }
    }
}
