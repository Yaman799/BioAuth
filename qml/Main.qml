import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import QtQuick.Effects
import "dialogs"
import "components"
import "theme/Ui.js" as Ui

ApplicationWindow {
    id: window
    width: 1280
    height: 820
    minimumWidth: 700
    minimumHeight: 520
    visible: true
    title: backend.tr("app_title")
    color: theme.window

    property bool isArabic: backend.language === "ar"
    property var theme: Ui.foundationTheme(backend.theme)
    property var selectedSession: ({})
    property string deletePasswordDraft: ""
    property string pendingDeleteSessionPath: ""
    property var pendingDeleteSessionPaths: []
    property var pendingFeedbackPrompt: ({})
    property bool compactWidth: width < 1180
    property bool denseWidth: width < 980
    property bool shortHeight: height < 760
    property real shellSidebarWidth: denseWidth ? 208 : (compactWidth ? 244 : 304)
    property bool pendingInterfaceTourStart: false
    property bool autoInterfaceTourAllowed: false
    property int pendingInterfaceTourAttempts: 0

    function scaled(base, minValue, maxValue) {
        var factor = Math.min(width / 1440, height / 920)
        var value = Math.round(base * factor)
        if (minValue !== undefined)
            value = Math.max(minValue, value)
        if (maxValue !== undefined)
            value = Math.min(maxValue, value)
        return value
    }

    function fitToAvailableScreen() {
        var availableWidth = Screen.desktopAvailableWidth || Screen.width || width
        var availableHeight = Screen.desktopAvailableHeight || Screen.height || height
        if (availableWidth <= 840 || availableHeight <= 620) {
            showMaximized()
            return
        }
        width = Math.max(minimumWidth, Math.min(1440, availableWidth - 72))
        height = Math.max(minimumHeight, Math.min(920, availableHeight - 72))
        x = Math.max(0, Math.round((availableWidth - width) / 2))
        y = Math.max(0, Math.round((availableHeight - height) / 2))
    }

    LayoutMirroring.enabled: isArabic
    LayoutMirroring.childrenInherit: true

    function trx(arText, enText) {
        return isArabic ? arText : enText
    }

    function userSafeStatusText(value, fallbackText) {
        // In user mode: delegate to backend.safeStatusMessage which uses the
        // single-source Python filter (src/bioauth/ui_state/safe_text.py).
        // Developer mode shows the raw text for diagnostics.
        var text = String(value || "")
        if (text.length === 0)
            return fallbackText || ""
        if (backend.uiMode !== "user")
            return text
        if (backend.userSafeStatusText !== undefined)
            return backend.userSafeStatusText(text, fallbackText || "")
        // Use the backend-filtered property when the value IS the current status message.
        // For other runtime text values, keep the simple keyword check as a fallback guard.
        if (text === backend.statusMessage && backend.safeStatusMessage !== undefined)
            return backend.safeStatusMessage || fallbackText || ""
        var lower = text.toLowerCase()
        var statusTerms = []
        var hasFilteredTerm = false
        for (var i = 0; i < statusTerms.length; i++) {
            if (lower.indexOf(statusTerms[i]) >= 0) {
                hasFilteredTerm = true
                break
            }
        }
        if (hasFilteredTerm) {
            if (lower.indexOf("suspicious") >= 0 || lower.indexOf("attention") >= 0)
                return trx("فحص الحماية يحتاج انتباهًا.", "Background check needs attention.")
            if (lower.indexOf("pending") >= 0 || lower.indexOf("waiting") >= 0 || lower.indexOf("collecting") >= 0)
                return trx("فحص الحماية جارٍ.", "Background check in progress.")
            return trx("فحص الحماية نشط.", "Background check active.")
        }
        return text
    }

    function syncOnboardingDialog() {
        if (backend.onboardingVisible) {
            if (!onboardingDialog.visible)
                onboardingDialog.open()
        } else if (onboardingDialog.visible) {
            onboardingDialog.close()
        }
    }

    function queueInterfaceTourStart() {
        pendingInterfaceTourStart = true
        pendingInterfaceTourAttempts = 0
        interfaceTourStartTimer.restart()
    }

    function modalBlocksInterfaceTour() {
        return onboardingDialog.visible
                || alertDialog.visible
                || feedbackPromptDialog.visible
                || shadowPromoteDialog.visible
                || appPasscodePopup.visible
                || passcodeSetupPrompt.visible
                || passcodeSetupDialog.visible
    }

    function tryStartPendingInterfaceTour() {
        if (!pendingInterfaceTourStart)
            return
        if (!backend.authenticated || backend.uiMode !== "user")
            return
        if (modalBlocksInterfaceTour()) {
            interfaceTourStartTimer.restart()
            return
        }
        if (!shellLoader.item || typeof shellLoader.item.startFirstRunGuide !== "function") {
            pendingInterfaceTourAttempts += 1
            if (pendingInterfaceTourAttempts < 60)
                interfaceTourStartTimer.restart()
            return
        }

        pendingInterfaceTourStart = false
        pendingInterfaceTourAttempts = 0
        shellLoader.item.startFirstRunGuide()
    }

    function toneColor(tone) {
        if (tone === "success") return theme.success
        if (tone === "warn" || tone === "warning") return theme.warn
        if (tone === "danger" || tone === "error") return theme.danger
        return theme.info
    }

    function appLockCooldownText() {
        var seconds = Number(backend.appPasscodeCooldownRemaining || 0)
        if (seconds <= 0)
            return ""
        return trx("حاول مجددًا بعد " + seconds + " ثانية.", "Try again in " + seconds + "s.")
    }

    function selectedShellComponent() {
        if (!backend.authenticated)
            return authPage
        return backend.uiMode === "user" ? userShell : appShell
    }

    function syncAppPasscodePopup() {
        var shouldShow = backend.authenticated && backend.appPasscodeLocked
        if (shouldShow) {
            if (!appPasscodePopup.visible)
                appPasscodePopup.open()
        } else if (appPasscodePopup.visible) {
            appPasscodePopup.close()
        }
    }

    function syncPasscodeSetupPrompt() {
        if (backend.passcodeSetupPromptVisible) {
            if (!passcodeSetupPrompt.visible)
                passcodeSetupPrompt.open()
        } else if (passcodeSetupPrompt.visible) {
            passcodeSetupPrompt.close()
        }
        if (!backend.passcodeSetupPromptVisible && passcodeSetupDialog.visible)
            passcodeSetupDialog.close()
    }

    function decisionTone(decision) {
        var v = String(decision || "").toLowerCase()
        if (v === "legit" || v === "authorized") return "success"
        if (v === "suspicious" || v === "warning") return "warn"
        if (v === "intruder" || v === "locked" || v === "blocked") return "danger"
        return "info"
    }

    function openSessionDetails(path) {
        selectedSession = backend.sessionDetails(path)
        sessionDialog.open()
    }

    function requestDeleteSession(path) {
        pendingDeleteSessionPath = path
        deleteSessionDialog.sessionPath = path
        deleteSessionDialog.open()
    }

    function requestDeleteSessions(paths) {
        pendingDeleteSessionPaths = paths || []
        if (!pendingDeleteSessionPaths || pendingDeleteSessionPaths.length === 0)
            return
        bulkDeleteDialog.open()
    }

    function bulkDeleteBodyText() {
        var count = pendingDeleteSessionPaths ? pendingDeleteSessionPaths.length : 0
        return trx(
                    "هل تريد حذف " + count + " جلسات محددة من الأرشيف المحلي؟",
                    "Delete " + count + " selected sessions from the local archive?"
                )
    }

    function openResetProfileConfirm() {
        resetConfirm.open()
    }

    function openDeleteAccountConfirm(password) {
        deletePasswordDraft = password
        deleteAccountDialog.passwordDraft = password
        deleteAccountDialog.open()
    }

    function openDeleteMyDataConfirm() {
        deleteMyDataConfirm.open()
    }

    function openDeleteIncidentEvidenceConfirm() {
        deleteIncidentEvidenceConfirm.open()
    }

    function toggleFullscreen() {
        if (window.visibility === Window.FullScreen)
            window.showNormal()
        else
            window.showFullScreen()
    }

    function dashboardWindowVisible() {
        return window.visible && window.visibility !== Window.Hidden && window.visibility !== Window.Minimized
    }

    function notifyDashboardVisibility() {
        if (backend && backend.setDashboardVisible)
            backend.setDashboardVisible(dashboardWindowVisible())
    }

    onVisibleChanged: notifyDashboardVisibility()
    onVisibilityChanged: notifyDashboardVisibility()

    Shortcut {
        sequence: "F11"
        context: Qt.ApplicationShortcut
        onActivated: window.toggleFullscreen()
    }

    Timer {
        id: interfaceTourStartTimer
        interval: 220
        repeat: false
        onTriggered: window.tryStartPendingInterfaceTour()
    }

    function driftTone(kind) {
        var ready = !!backend.profile.ready
        var flow = String(backend.runtimeState.flow || "").toLowerCase()
        var decision = String(backend.runtimeState.decisionText || "").toLowerCase()
        if (!ready)
            return "neutral"
        if (backend.runtimeState.technicalFailure)
            return "danger"
        if (backend.runtimeState.awaitingEvidence)
            return kind === "combined" ? "warn" : "info"
        if (decision === "intruder" || flow === "protected_forced_stop")
            return "danger"
        if (decision === "suspicious")
            return kind === "combined" ? "danger" : "warn"
        if (backend.runtimeState.active)
            return kind === "combined" ? "info" : "success"
        return kind === "combined" ? "success" : "info"
    }

    function driftLabel(kind) {
        var ready = !!backend.profile.ready
        var decision = String(backend.runtimeState.decisionText || "").toLowerCase()
        if (!ready)
            return trx("بانتظار baseline", "Waiting for baseline")
        if (backend.runtimeState.technicalFailure)
            return backend.runtimeState.statusLabel || trx("خلل تقني", "Technical issue")
        if (backend.runtimeState.awaitingEvidence)
            return backend.runtimeState.runtimeDisplayText || backend.runtimeState.statusLabel || trx("جمع الأدلة", "Collecting evidence")
        if (decision === "intruder")
            return trx("مختلف بشكل ملحوظ", "Clearly different")
        if (decision === "suspicious")
            return kind === "combined" ? trx("مختلف بشكل ملحوظ", "Clearly different") : trx("متحول قليلًا", "Slightly shifted")
        return trx("طبيعي", "Normal")
    }

    function driftDescription(kind) {
        if (!backend.profile.ready)
            return trx("هذا القسم أصبح Preview تجريبيًا يعرض فقط الحالة الحقيقية المتاحة من الـ backend بدل أي محرك drift غير مكتمل.", "This section is now an experimental preview that only shows real backend state instead of an incomplete drift engine.")
        if (kind === "keyboard")
            return trx("إيقاع الكتابة والتوقفات والسرعة مقارنة بآخر جلساتك الموثوقة.", "Keyboard rhythm, pauses, and speed compared with recent trusted sessions.")
        if (kind === "mouse")
            return trx("حركة المؤشر والسلاسة والانتقالات مقارنة بالنمط المعتاد.", "Pointer motion, smoothness, and transitions versus your usual pattern.")
        return trx("المشهد العام للسلوك اليومي مقارنة بخلاصة baseline الأخيرة.", "Overall daily behavior compared against your recent baseline.")
    }

    AlertDialog {
        id: alertDialog
        rootWindow: window
        onVisibleChanged: {
            if (!visible && window.pendingInterfaceTourStart)
                interfaceTourStartTimer.restart()
        }
    }

    SessionDialog {
        id: sessionDialog
        rootWindow: window
        sessionData: window.selectedSession
    }

    ConfirmDialog {
        id: resetConfirm
        rootWindow: window
        bodyText: backend.tr("confirm_reset")
        confirmText: backend.tr("reset_profile")
        tone: "danger"
        onConfirmed: backend.resetProfile()
    }

    DeleteAccountDialog {
        id: deleteAccountDialog
        rootWindow: window
        passwordDraft: window.deletePasswordDraft
        onConfirmed: function(password) {
            backend.deleteAccount(password)
            window.deletePasswordDraft = ""
        }
    }

    ConfirmDialog {
        id: deleteMyDataConfirm
        rootWindow: window
        bodyText: backend.tr("confirm_delete_my_data")
        confirmText: backend.tr("delete_my_data")
        tone: "danger"
        onConfirmed: backend.deleteMyData()
    }

    ConfirmDialog {
        id: deleteIncidentEvidenceConfirm
        rootWindow: window
        bodyText: window.trx(
                      "هل تريد حذف أدلة الحوادث المحلية لهذا الحساب؟ لن يتم حذف الحساب أو الجلسات.",
                      "Delete local incident evidence for this account? This does not delete the account or session history."
                  )
        confirmText: window.trx("حذف أدلة الحوادث", "Delete incident evidence")
        cancelText: window.trx("إلغاء", "Cancel")
        tone: "warn"
        onConfirmed: backend.deleteIncidentEvidence()
    }

    DeleteSessionDialog {
        id: deleteSessionDialog
        rootWindow: window
        onConfirmed: function(sessionPath) { backend.deleteSession(sessionPath) }
    }

    ConfirmDialog {
        id: bulkDeleteDialog
        rootWindow: window
        bodyText: window.bulkDeleteBodyText()
        confirmText: window.trx("حذف المحدد", "Delete selected")
        cancelText: window.trx("إلغاء", "Cancel")
        tone: "danger"
        onConfirmed: {
            backend.deleteSessions(window.pendingDeleteSessionPaths)
            window.pendingDeleteSessionPaths = []
        }
        onRejected: {
            window.pendingDeleteSessionPaths = []
        }
    }

    ConfirmDialog {
        id: shadowPromoteDialog
        rootWindow: window
        bodyText: window.trx(
                      "تم إعداد تحديث جديد من جلساتك الموثوقة وأظهر أداءً أفضل بشكل مستمر. متوسط التحسن الحالي: " + Number(backend.shadowStatus.pending_avg_delta || backend.shadowStatus.avg_delta || 0).toFixed(1) + " نقطة مخاطرة أقل. هذا المسار يسجل حالة الأدلة فقط ولا يفعّل الإنتاج حتى يمر باعتماد الإنتاج وموافقة صريحة لاحقة.",
                      "A new model update trained from your recent trusted sessions has consistently scored better. Current average improvement: " + Number(backend.shadowStatus.pending_avg_delta || backend.shadowStatus.avg_delta || 0).toFixed(1) + " lower risk points. This path records evidence status only and cannot activate production until production approval and a later explicit approval step pass."
                  )
        confirmText: window.trx("متابعة التحقق", "Continue validation")
        cancelText: window.trx("لاحقًا", "Later")
        tone: "info"
        onConfirmed: backend.promoteShadowModel()
        onRejected: backend.dismissShadowSuggestion()
    }

    OnboardingDialog {
        id: onboardingDialog
        rootWindow: window
        onNewUserSlidesFinished: function(skipped) {
            window.autoInterfaceTourAllowed = !skipped
            if (!skipped)
                window.queueInterfaceTourStart()
        }
    }

    Dialog {
        id: feedbackPromptDialog
        parent: Overlay.overlay
        modal: true
        anchors.centerIn: parent
        width: Math.min(window.width - 48, 560)
        padding: 0
        title: backend.tr("post_lock_confirmation_title")
        background: GlassCard { }
        contentItem: ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 14
            Label {
                text: backend.tr("post_lock_confirmation_body")
                color: theme.muted
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
            Flow {
                Layout.fillWidth: true
                spacing: 10
                AppButton {
                    text: backend.tr("post_lock_it_was_me")
                    role: "success"
                    onClicked: { backend.submitWarningFeedback("verified_legit_after_warning"); feedbackPromptDialog.close() }
                }
                AppButton {
                    text: backend.tr("post_lock_someone_else")
                    role: "danger"
                    onClicked: { backend.submitWarningFeedback("confirmed_intruder"); feedbackPromptDialog.close() }
                }
                AppButton {
                    visible: false
                    text: backend.tr("feedback_ignore_now")
                    role: "neutral"
                    onClicked: { feedbackPromptDialog.close() }
                }
            }
        }
    }

    ConfirmDialog {
        id: passcodeSetupPrompt
        rootWindow: window
        bodyText: backend.tr("passcode_setup_body")
        confirmText: backend.tr("enable_passcode_now")
        cancelText: backend.tr("passcode_later")
        tone: "info"
        onConfirmed: passcodeSetupDialog.open()
        onRejected: backend.dismissPasscodeSetupPrompt()
        onVisibleChanged: {
            if (!visible && window.pendingInterfaceTourStart)
                interfaceTourStartTimer.restart()
        }
    }

    Dialog {
        id: passcodeSetupDialog
        parent: Overlay.overlay
        onVisibleChanged: {
            if (!visible && window.pendingInterfaceTourStart)
                interfaceTourStartTimer.restart()
        }
        modal: true
        anchors.centerIn: parent
        width: Math.min(window.width - 48, 520)
        padding: 0
        title: backend.tr("passcode_setup_title")
        background: GlassCard { }
        onClosed: {
            setupPasscodeField.text = ""
            setupPasscodeConfirmField.text = ""
            if (!backend.appPasscodeConfigured)
                backend.dismissPasscodeSetupPrompt()
        }
        contentItem: ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 14
            Label {
                text: backend.tr("passcode_setup_body")
                color: theme.muted
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }
            AppTextField {
                id: setupPasscodeField
                Layout.fillWidth: true
                placeholderText: backend.tr("app_passcode_new")
                echoMode: TextInput.Password
                inputMethodHints: Qt.ImhDigitsOnly | Qt.ImhSensitiveData
            }
            AppTextField {
                id: setupPasscodeConfirmField
                Layout.fillWidth: true
                placeholderText: backend.tr("app_passcode_confirm")
                echoMode: TextInput.Password
                inputMethodHints: Qt.ImhDigitsOnly | Qt.ImhSensitiveData
                onAccepted: saveSetupPasscodeButton.clicked()
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 12
                AppButton {
                    text: backend.tr("passcode_later")
                    role: "neutral"
                    Layout.fillWidth: true
                    onClicked: { backend.dismissPasscodeSetupPrompt(); passcodeSetupDialog.close() }
                }
                AppButton {
                    id: saveSetupPasscodeButton
                    text: backend.tr("app_passcode_save")
                    role: "details"
                    Layout.fillWidth: true
                    onClicked: {
                        backend.updateAppPasscode("", setupPasscodeField.text, setupPasscodeConfirmField.text)
                        if (backend.appPasscodeConfigured) {
                            backend.dismissPasscodeSetupPrompt()
                            passcodeSetupDialog.close()
                        }
                    }
                }
            }
        }
    }

    Popup {
        id: appPasscodePopup
        parent: Overlay.overlay
        modal: true
        focus: visible
        closePolicy: Popup.NoAutoClose
        anchors.centerIn: parent
        width: Math.min(window.width - 36, 520)
        padding: 0

        Overlay.modal: Rectangle {
            color: theme.isDark ? "#c608101c" : "#aa0d1626"
        }

        onOpened: {
            unlockField.text = ""
            unlockField.forceActiveFocus()
        }

        background: Rectangle {
            radius: 28
            color: theme.surface
            border.color: theme.border
            border.width: 1
        }

        contentItem: ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                spacing: 14

                Rectangle {
                    implicitWidth: 58
                    implicitHeight: 58
                    radius: 18
                    color: theme.disabledBg
                    border.color: theme.border
                    border.width: 1

                    Label {
                        anchors.centerIn: parent
                        text: "🔒"
                        font.pixelSize: 24
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4
                    Label {
                        text: backend.tr("app_passcode_overlay_title")
                        color: theme.text
                        font.pixelSize: 28
                        font.bold: true
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Label {
                        text: backend.tr("app_passcode_overlay_body")
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 74
                radius: 18
                color: theme.surface1
                border.color: theme.border
                border.width: 1

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 6
                    Label {
                        text: backend.tr("app_passcode_overlay_hint")
                        color: theme.text
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Label {
                        text: trx("تستمر الحماية ومراقبة الجلسات بدون انقطاع أثناء قفل الواجهة.", "Protection and session monitoring continue without interruption while the interface is locked.")
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                }
            }

            AppTextField {
                id: unlockField
                Layout.fillWidth: true
                placeholderText: backend.tr("app_passcode_current")
                echoMode: TextInput.Password
                inputMethodHints: Qt.ImhDigitsOnly | Qt.ImhSensitiveData
                onAccepted: backend.unlockAppPasscode(text)
            }

            Label {
                Layout.fillWidth: true
                text: backend.appPasscodeMessage !== "" ? backend.appPasscodeMessage : window.appLockCooldownText()
                color: backend.appPasscodeCooldownRemaining > 0 ? theme.warn : theme.danger
                visible: text !== ""
                wrapMode: Text.Wrap
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 12

                AppButton {
                    text: backend.tr("app_passcode_unlock")
                    role: "details"
                    Layout.fillWidth: true
                    onClicked: backend.unlockAppPasscode(unlockField.text)
                }
                AppButton {
                    text: backend.tr("logout")
                    role: "danger"
                    Layout.fillWidth: true
                    onClicked: backend.logout()
                }
            }
        }
    }

    Connections {
        target: backend
        function onDialogMessage(title, message, level) {
            alertDialog.title = title
            alertDialog.body = message
            alertDialog.tone = level
            alertDialog.open()
        }
        function onWarningFeedbackPromptRequested(payload) {
            var prompt = payload || ({})
            if (!prompt || prompt.kind !== "post_lock_confirmation")
                return
            window.pendingFeedbackPrompt = prompt
            if (!feedbackPromptDialog.visible)
                feedbackPromptDialog.open()
        }
        function onShadowChanged() {
            if (backend.shadowStatus.promote_suggested && backend.shadowStatus.suggestion_pending) {
                if (!shadowPromoteDialog.visible)
                    shadowPromoteDialog.open()
            } else if (shadowPromoteDialog.visible) {
                shadowPromoteDialog.close()
            }
        }
        function onOnboardingChanged() {
            window.syncOnboardingDialog()
            if (!backend.onboardingVisible && window.autoInterfaceTourAllowed) {
                window.autoInterfaceTourAllowed = false
                window.queueInterfaceTourStart()
            }
        }
        function onAppPasscodeChanged() {
            window.syncAppPasscodePopup()
            if (backend.appPasscodeConfigured && backend.passcodeSetupPromptVisible)
                backend.dismissPasscodeSetupPrompt()
            if (window.pendingInterfaceTourStart)
                interfaceTourStartTimer.restart()
        }
        function onPasscodeSetupPromptChanged() {
            window.syncPasscodeSetupPrompt()
            if (window.pendingInterfaceTourStart)
                interfaceTourStartTimer.restart()
        }
        function onAuthenticatedChanged() {
            window.syncAppPasscodePopup()
            if (window.pendingInterfaceTourStart)
                interfaceTourStartTimer.restart()
        }
        function onUiModeChanged() {
            if (window.pendingInterfaceTourStart)
                interfaceTourStartTimer.restart()
        }
    }

    Component.onCompleted: { fitToAvailableScreen(); syncOnboardingDialog(); syncAppPasscodePopup(); syncPasscodeSetupPrompt(); notifyDashboardVisibility() }

    Item {
        id: appContentLayer
        anchors.fill: parent
        layer.enabled: onboardingDialog.visible
        layer.smooth: onboardingDialog.visible
        layer.effect: MultiEffect {
            blurEnabled: onboardingDialog.visible
            blurMax: 24
            blur: onboardingDialog.visible ? 0.78 : 0.0
            autoPaddingEnabled: false
        }

        Item {
            anchors.fill: parent
            layer.enabled: true
            layer.smooth: false

            Rectangle {
                anchors.fill: parent
                color: theme.surface0 || theme.window
            }

            Rectangle {
                width: window.width * 0.45
                height: window.height * 0.6
                radius: width / 2
                x: isArabic ? window.width * 0.62 : -width * 0.12
                y: -height * 0.18
                color: theme.accent
                opacity: theme.isDark ? 0.10 : 0.07
            }

            Rectangle {
                width: window.width * 0.38
                height: window.height * 0.48
                radius: width / 2
                x: isArabic ? -width * 0.1 : window.width * 0.72
                y: window.height * 0.56
                color: theme.primary
                opacity: theme.isDark ? 0.12 : 0.08
            }

            Rectangle {
                anchors.fill: parent
                gradient: Gradient {
                    GradientStop { position: 0.0; color: theme.overlayTint || "#66ffffff" }
                    GradientStop { position: 1.0; color: "transparent" }
                }
            }
        }

        Loader {
            id: shellLoader
            anchors.fill: parent
            asynchronous: true
            sourceComponent: window.selectedShellComponent()
            onLoaded: window.tryStartPendingInterfaceTour()
        }
    }

    Component {
        id: authPage
        AuthPage { rootWindow: window }
    }

    Component {
        id: appShell
        AppShell { windowRef: window }
    }

    Component {
        id: userShell
        UserShell { windowRef: window }
    }

    footer: Item {
        height: backend.statusMessage.length > 0 ? 42 : 0
        Behavior on height { NumberAnimation { duration: 180 } }

        Rectangle {
            anchors.fill: parent
            anchors.leftMargin: 18
            anchors.rightMargin: 18
            anchors.topMargin: 5
            anchors.bottomMargin: 7
            radius: 15
            color: theme.surface1 || theme.surface
            border.color: theme.neutralBorder || theme.border
            border.width: 1
            opacity: backend.statusMessage.length > 0 ? 0.96 : 0.0
            Behavior on opacity { NumberAnimation { duration: 180 } }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 14
                anchors.topMargin: 6
                anchors.bottomMargin: 6
                spacing: 9

                Rectangle {
                    Layout.preferredWidth: 8
                    Layout.preferredHeight: 8
                    radius: 4
                    color: window.toneColor(backend.statusTone)
                    opacity: theme.isDark ? 0.82 : 0.72
                }

                Label {
                    Layout.fillWidth: true
                    text: window.userSafeStatusText(backend.statusMessage)
                    color: theme.text
                    font.bold: false
                    font.pixelSize: 12
                    wrapMode: Text.Wrap
                    horizontalAlignment: window.isArabic ? Text.AlignRight : Text.AlignLeft
                    verticalAlignment: Text.AlignVCenter
                    maximumLineCount: 2
                    elide: Text.ElideRight
                }
            }
        }
    }
}
