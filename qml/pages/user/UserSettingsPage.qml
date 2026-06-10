import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"
import "../settings"
import "../../theme/Ui.js" as Ui

ScrollView {
    id: root
    clip: true
    contentWidth: Math.max(0, availableWidth)
    contentHeight: settingsContent.implicitHeight
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property bool settingsActionInFlight: false
    property string activeSection: "general"
    property bool showFaceAdvancedSettings: false
    property bool generalDraftsReady: false
    property bool generalApplyInFlight: false
    property string draftTheme: "dark"
    property string draftLanguage: "en"
    property bool draftButtonSoundsMuted: false
    property bool draftRunOnStartup: false
    property bool draftRememberLoginEnabled: false
    property string generalFeedbackText: ""
    property string generalFeedbackTone: "neutral"
    property var pendingGeneralRequest: ({})
    property bool securityDraftsReady: false
    property bool securityApplyInFlight: false
    property bool draftAppPasscodeEnabled: false
    property int draftAppPasscodeTimeoutSec: 60
    property string securityFeedbackText: ""
    property string securityFeedbackTone: "neutral"
    property var pendingSecurityRequest: ({})
    property var currentPasscodeField: null
    property var newPasscodeField: null
    property var confirmPasscodeField: null
    property bool accountSecurityActionInFlight: false
    property string accountSecurityFeedbackText: ""
    property string accountSecurityFeedbackTone: "neutral"
    property var currentAccountPasswordField: null
    property var newAccountPasswordField: null
    property var confirmAccountPasswordField: null
    property var recoveryPasswordField: null
    property bool privacyDraftsReady: false
    property bool privacyApplyInFlight: false
    property bool draftIncidentEvidenceEnabled: false
    property bool draftIncidentEvidenceCaptureScreenshot: true
    property bool draftIncidentEvidenceCaptureWebcam: true
    property int draftIncidentEvidenceRetentionDays: 30
    property string privacyFeedbackText: ""
    property string privacyFeedbackTone: "neutral"
    property var pendingPrivacyRequest: ({})
    property bool licenseActionInFlight: false
    property string licenseFeedbackText: ""
    property string licenseFeedbackTone: "neutral"
    property var licenseCodeField: null
    property var licensePathField: null
    property bool updateActionInFlight: false
    property string updateFeedbackText: ""
    property string updateFeedbackTone: "neutral"
    property bool deviceDraftsReady: false
    property bool deviceApplyInFlight: false
    property bool deviceBenchmarkInFlight: false
    property string draftDeepRuntimeMode: "auto"
    property string deviceFeedbackText: ""
    property string deviceFeedbackTone: "neutral"
    property var pendingDeviceRequest: ({})

    readonly property bool denseLayout: width < 980
    readonly property bool compactLayout: width < 760
    readonly property bool compactPage: compactLayout
    readonly property int sectionChipHeight: denseLayout ? 38 : 40
    readonly property bool isArabic: backend.language === "ar"
    readonly property var faceState: backend.faceConfirmationState || ({})
    readonly property var privacyState: backend.privacyCenterState || ({})
    readonly property var learningState: backend.autoEnrollmentState || ({})
    readonly property var benchmarkState: backend.deepRuntimeBenchmark || ({})
    readonly property var updateState: backend.updateState || ({})
    readonly property var licenseState: backend.licenseStatus || ({})
    readonly property bool benchmarkReady: root.benchmarkState && root.benchmarkState.status === "ok"
    readonly property bool faceEnrollmentFeatureEnabled: faceState.faceEnrollmentFeatureEnabled === true
    readonly property bool faceConfirmationFeatureEnabled: faceState.faceConfirmationFeatureEnabled === true
    readonly property bool hasGeneralDraftChanges: root.generalDraftsReady && (
        root.draftTheme !== backend.themeMode
        || root.draftLanguage !== backend.language
        || root.draftButtonSoundsMuted !== backend.buttonSoundsMuted
        || root.draftRunOnStartup !== backend.runOnStartup
        || root.draftRememberLoginEnabled !== backend.rememberLoginEnabled
    )
    readonly property bool hasSecurityPasscodeDraftText: (
        (root.currentPasscodeField && root.currentPasscodeField.text.length > 0)
        || (root.newPasscodeField && root.newPasscodeField.text.length > 0)
        || (root.confirmPasscodeField && root.confirmPasscodeField.text.length > 0)
    )
    readonly property bool hasSecurityDraftChanges: root.securityDraftsReady && (
        root.draftAppPasscodeEnabled !== backend.appPasscodeEnabled
        || root.draftAppPasscodeTimeoutSec !== backend.appPasscodeTimeoutSec
        || root.hasSecurityPasscodeDraftText
    )
    readonly property bool hasPrivacyDraftChanges: root.privacyDraftsReady && (
        root.draftIncidentEvidenceEnabled !== backend.incidentEvidenceEnabled
        || root.draftIncidentEvidenceCaptureScreenshot !== backend.incidentEvidenceCaptureScreenshot
        || root.draftIncidentEvidenceCaptureWebcam !== backend.incidentEvidenceCaptureWebcam
        || root.draftIncidentEvidenceRetentionDays !== backend.incidentEvidenceRetentionDays
    )
    readonly property bool hasDeviceDraftChanges: root.deviceDraftsReady && (
        root.draftDeepRuntimeMode !== root.safeString(backend.deepRuntimeMode, "auto")
    )
    readonly property bool faceOperationInFlight: faceState.faceOperationInFlight === true || faceState.operationInFlight === true
    readonly property var calmToggleTheme: ({
        "accent": Ui.roleColor(theme, "success"),
        "switchOffBg": Ui.colorToken(theme, "switchOffBg"),
        "surface2": Ui.colorToken(theme, "surface2"),
        "border": Ui.colorToken(theme, "border")
    })

    readonly property url faceHero: Qt.resolvedUrl("../../assets/bioauth/01_hero_integrated/05_face_identity_integrated.png")
    readonly property url preferencesIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/34_preferences.png")
    readonly property url faceIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/03_face_scan.png")
    readonly property url privacyIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/06_privacy_lock.png")
    readonly property url localDataIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/12_local_data.png")
    readonly property url consentIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/11_consent_user_check.png")
    readonly property url retentionIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/14_retention_calendar.png")
    readonly property url deviceIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/07_device_fit.png")
    readonly property url compatibilityIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/32_compatibility.png")
    readonly property url settingsIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/05_settings_gear.png")
    readonly property url updateIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/04_updates_refresh.png")
    readonly property url securityIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/28_verification_shield.png")
    readonly property url storageIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/30_secure_storage.png")
    readonly property url infoIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/22_info.png")
    readonly property url warningIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/19_warning.png")

    LayoutMirroring.enabled: root.isArabic
    LayoutMirroring.childrenInherit: true

    Timer {
        id: settingsGuardTimer
        interval: 800
        repeat: false
        onTriggered: {
            if (!root.generalApplyInFlight && !root.securityApplyInFlight && !root.privacyApplyInFlight && !root.licenseActionInFlight && !root.updateActionInFlight && !root.deviceApplyInFlight && !root.deviceBenchmarkInFlight && !root.accountSecurityActionInFlight)
                root.settingsActionInFlight = false
        }
    }

    Timer {
        id: generalApplyFinishTimer
        interval: 280
        repeat: false
        onTriggered: root.finishGeneralApply()
    }

    Timer {
        id: securityApplyFinishTimer
        interval: 320
        repeat: false
        onTriggered: root.finishSecurityApply()
    }

    Timer {
        id: privacyApplyFinishTimer
        interval: 320
        repeat: false
        onTriggered: root.finishPrivacyApply()
    }

    Timer {
        id: licenseActionGuardTimer
        interval: 900
        repeat: false
        onTriggered: {
            root.licenseActionInFlight = false
            if (!root.generalApplyInFlight && !root.securityApplyInFlight && !root.privacyApplyInFlight && !root.updateActionInFlight && !root.deviceApplyInFlight && !root.deviceBenchmarkInFlight && !root.accountSecurityActionInFlight)
                root.settingsActionInFlight = false
        }
    }

    Timer {
        id: updateActionGuardTimer
        interval: 6000
        repeat: false
        onTriggered: {
            root.updateActionInFlight = false
            if (!root.generalApplyInFlight && !root.securityApplyInFlight && !root.privacyApplyInFlight && !root.licenseActionInFlight && !root.deviceApplyInFlight && !root.deviceBenchmarkInFlight && !root.accountSecurityActionInFlight)
                root.settingsActionInFlight = false
        }
    }

    Timer {
        id: deviceApplyFinishTimer
        interval: 340
        repeat: false
        onTriggered: root.finishDeviceApply()
    }

    Timer {
        id: deviceBenchmarkGuardTimer
        interval: 1200
        repeat: false
        onTriggered: root.finishDeviceBenchmark()
    }

    Timer {
        id: accountSecurityActionGuardTimer
        interval: 900
        repeat: false
        onTriggered: root.finishAccountSecurityAction()
    }

    function label(arText, enText) {
        return Ui.trx(root.isArabic, arText, enText)
    }

    function tourTarget(name) {
        if (name === "settingsHero") return settingsHeroCard
        return null
    }

    function startInterfaceGuideFromSettings() {
        if (root.rootWindow && typeof root.rootWindow.startInterfaceGuide === "function")
            root.rootWindow.startInterfaceGuide()
    }

    function trx(arText, enText) {
        return root.label(arText, enText)
    }

    function safeString(value, fallbackText) {
        var text = String(value === undefined || value === null ? "" : value)
        return text.length > 0 ? text : (fallbackText || "")
    }

    function yesNo(value) {
        return value === true ? backend.tr("enabled") : backend.tr("disabled")
    }

    function userSafeText(value, fallbackText) {
        var text = String(value || "")
        if (text.length === 0)
            return fallbackText || ""
        var lower = text.toLowerCase()
        if (lower.indexOf("model") >= 0 && lower.indexOf("file") >= 0 && lower.indexOf("missing") >= 0)
            return root.label("تأكيد الوجه يحتاج إلى إعداد", "Face confirmation needs setup")
        if (lower.indexOf("sha" + "dow") >= 0)
            return root.label("فحص الحماية جارٍ", "Background check in progress")
        if (lower.indexOf("fallback") >= 0)
            return root.label("يستخدم التطبيق وضع توافق مناسب لهذا الجهاز.", "The app is using a compatibility mode for this device.")
        return text
    }

    function licenseStateSummary() {
        var state = String(root.licenseState.state || "")
        if (state.length === 0)
            return root.label("لا توجد حالة ترخيص معروضة حالياً.", "No license state is shown right now.")
        if (state === "licensed")
            return root.label("ترخيص نشط حسب حالة النظام.", "License is active according to system state.")
        if (state === "trial_active")
            return root.label("الفترة التجريبية نشطة حسب حالة النظام.", "Trial is active according to system state.")
        if (state === "grace_active")
            return root.label("فترة السماح نشطة حسب حالة النظام.", "Grace period is active according to system state.")
        if (state.indexOf("expired") >= 0)
            return root.label("الترخيص منتهي حسب حالة النظام.", "License is expired according to system state.")
        if (state.indexOf("invalid") >= 0 || state.indexOf("malformed") >= 0)
            return root.label("الترخيص غير صالح حسب حالة النظام.", "License is invalid according to system state.")
        return state
    }

    function updateStateSummary() {
        var status = String(root.updateState.status || "")
        var message = String(root.updateState.message || "")
        if (status.length > 0 && message.length > 0)
            return status + " — " + message
        if (status.length > 0)
            return status
        if (message.length > 0)
            return message
        return root.label("لا توجد حالة تحديث معروضة حالياً.", "No update status is shown right now.")
    }

    function themeLabel(mode) {
        return String(mode || "dark") === "light" ? root.label("فاتح", "Light") : root.label("داكن", "Dark")
    }

    function languageLabel(code) {
        return String(code || "en") === "ar" ? root.label("العربية", "Arabic") : "English"
    }

    function buttonSoundsLabel(muted) {
        return muted === true ? root.label("مكتومة", "Muted") : root.label("مفعّلة", "Enabled")
    }

    function generalFeedbackFallback() {
        if (root.generalApplyInFlight)
            return root.label("جاري حفظ التغييرات…", "Applying changes…")
        if (root.hasGeneralDraftChanges)
            return root.label("توجد تغييرات غير محفوظة.", "You have unsaved changes.")
        return root.label("القيم الحالية متزامنة مع إعدادات النظام.", "Current values match system settings.")
    }

    function generalFeedbackCurrentTone() {
        if (root.generalApplyInFlight)
            return "info"
        if (root.generalFeedbackText.length > 0)
            return root.generalFeedbackTone
        return root.hasGeneralDraftChanges ? "warn" : "success"
    }

    function securityFeedbackFallback() {
        if (root.securityApplyInFlight)
            return root.label("جاري تحديث إعدادات الأمان…", "Updating security settings…")
        if (root.hasSecurityDraftChanges)
            return root.label("توجد تغييرات أمان غير محفوظة أو حقول رمز دخول قيد التحرير.", "Security changes or passcode fields are pending.")
        return root.label("حالة الأمان المعروضة متزامنة مع النظام.", "Displayed security state matches the system.")
    }

    function securityFeedbackCurrentTone() {
        if (root.securityApplyInFlight)
            return "info"
        if (root.securityFeedbackText.length > 0)
            return root.securityFeedbackTone
        return root.hasSecurityDraftChanges ? "warn" : "success"
    }

    function accountSecurityFeedbackFallback() {
        if (root.accountSecurityActionInFlight)
            return root.label("جاري إرسال طلب أمان الحساب…", "Sending account security request…")
        if (backend.currentUser && backend.currentUser.password_recovery_ready === true)
            return root.label("كود الاسترداد المحلي جاهز لهذا الحساب.", "A local recovery code is ready for this account.")
        return root.label("يمكنك تحديث كلمة المرور أو إنشاء كود استرداد محلي من هنا.", "You can update the password or create a local recovery code here.")
    }

    function accountSecurityFeedbackCurrentTone() {
        if (root.accountSecurityActionInFlight)
            return "info"
        if (root.accountSecurityFeedbackText.length > 0)
            return root.accountSecurityFeedbackTone
        if (backend.currentUser && backend.currentUser.password_recovery_ready === true)
            return "success"
        return "neutral"
    }

    function recoveryStatusLabel() {
        if (backend.currentUser && backend.currentUser.password_recovery_ready === true)
            return root.label("مُعدّ", "Ready")
        return root.label("غير مُعدّ", "Not set")
    }

    function timeoutLabel(seconds) {
        var value = Number(seconds || 60)
        if (value === 60)
            return root.label("دقيقة واحدة", "1 minute")
        if (value === 300)
            return root.label("5 دقائق", "5 minutes")
        if (value === 900)
            return root.label("15 دقيقة", "15 minutes")
        if (value === 1800)
            return root.label("30 دقيقة", "30 minutes")
        return String(value) + " " + root.label("ثانية", "sec")
    }

    function deepRuntimeModeTitle(mode) {
        var value = root.safeString(mode, "auto")
        if (value === "classic")
            return root.label("خفيف", "Light")
        if (value === "hybrid")
            return root.label("حماية محسّنة", "Enhanced protection")
        if (value === "hybrid_accelerated")
            return root.label("حماية محسّنة أسرع", "Faster enhanced")
        return root.label("ذكي", "Smart")
    }

    function deepRuntimeModeDescription(mode) {
        var value = root.safeString(mode, "auto")
        if (value === "classic")
            return root.label("أقل حمل على الجهاز ويستخدم المحرك الأساسي فقط.", "Lowest device load and uses the core engine only.")
        if (value === "hybrid")
            return root.label("يضيف تحليلًا سلوكيًا أعمق وقد يستهلك موارد أكثر.", "Adds deeper behavior analysis and may use more resources.")
        if (value === "hybrid_accelerated")
            return root.label("يحاول استخدام المسار المحسّن الأسرع عند توفره، مع رجوع آمن حسب حالة النظام.", "Tries the faster enhanced path when available, with system-controlled fallback.")
        return root.label("يدع BioAuth يختار الوضع الأنسب حسب فحص الجهاز وحالة النظام.", "Lets BioAuth choose the best fit based on the device check and system state.")
    }

    function deepRuntimeModeBadge(mode) {
        var value = root.safeString(mode, "auto")
        if (value === "classic")
            return "LITE"
        if (value === "hybrid")
            return "PLUS"
        if (value === "hybrid_accelerated")
            return "FAST"
        return "AUTO"
    }

    function deviceFeedbackFallback() {
        if (root.deviceApplyInFlight)
            return root.label("جاري حفظ وضع الجهاز…", "Applying device mode…")
        if (root.deviceBenchmarkInFlight)
            return root.label("جاري تشغيل فحص الجهاز…", "Running device check…")
        if (root.hasDeviceDraftChanges)
            return root.label("توجد تغييرات غير محفوظة في وضع الجهاز.", "Device mode changes are pending.")
        return root.label("وضع الجهاز متزامن مع الحالة المؤكدة من النظام.", "Device mode matches confirmed system state.")
    }

    function deviceFeedbackCurrentTone() {
        if (root.deviceApplyInFlight || root.deviceBenchmarkInFlight)
            return "info"
        if (root.deviceFeedbackText.length > 0)
            return root.deviceFeedbackTone
        return root.hasDeviceDraftChanges ? "warn" : "success"
    }

    function benchmarkStatusText() {
        if (root.benchmarkReady)
            return root.label("آخر فحص مكتمل. الوضع المقترح: ", "Last check complete. Recommended mode: ") + root.deepRuntimeModeTitle(backend.deepRuntimeRecommendedMode)
        var status = root.safeString(root.benchmarkState.status, "")
        if (status.length > 0 && status !== "not_run")
            return root.userSafeText(root.benchmarkState.statusText, status)
        return root.label("لم يتم تشغيل فحص الجهاز بعد من هذه الصفحة.", "No device check has been run from this page yet.")
    }

    function passcodeConfiguredLabel() {
        if (backend.appPasscodeConfigured === true)
            return root.label("رمز الدخول مُعدّ حسب النظام.", "A passcode is configured according to the system.")
        return root.label("لم يتم إعداد رمز دخول بعد.", "No app passcode is configured yet.")
    }

    function retentionLabel(days) {
        var value = Number(days || 30)
        if (value === 7)
            return root.label("7 أيام", "7 days")
        if (value === 30)
            return root.label("30 يوم", "30 days")
        if (value === 90)
            return root.label("90 يوم", "90 days")
        return String(value) + " " + root.label("يوم", "days")
    }

    function privacyFeedbackFallback() {
        if (root.privacyApplyInFlight)
            return root.label("جاري حفظ إعدادات الخصوصية…", "Applying privacy settings…")
        if (root.hasPrivacyDraftChanges)
            return root.label("توجد تغييرات خصوصية غير محفوظة.", "Privacy changes are pending.")
        return root.label("إعدادات الخصوصية متزامنة مع الحالة المؤكدة من النظام.", "Privacy settings match confirmed system state.")
    }

    function privacyFeedbackCurrentTone() {
        if (root.privacyApplyInFlight)
            return "info"
        if (root.privacyFeedbackText.length > 0)
            return root.privacyFeedbackTone
        return root.hasPrivacyDraftChanges ? "warn" : "success"
    }

    function licenseStateTone() {
        var state = String(root.licenseState.state || "")
        if (state === "licensed" || state === "trial_active")
            return "success"
        if (state === "grace_active")
            return "warn"
        if (state.indexOf("expired") >= 0 || state.indexOf("invalid") >= 0 || state.indexOf("malformed") >= 0)
            return "danger"
        return "info"
    }

    function updateStateTone() {
        var state = String(root.updateState.state || "")
        if (state === "ready_to_install" || state === "up_to_date")
            return "success"
        if (state === "checking" || state === "downloading")
            return "info"
        if (state === "download_failed" || state === "hash_verification_failed" || state === "invalid_update_manifest" || state === "install_failed")
            return "danger"
        if (state === "update_available")
            return "warn"
        return "neutral"
    }

    function updateOperationActive() {
        var state = String(root.updateState.state || "")
        return root.updateActionInFlight || state === "checking" || state === "downloading"
    }

    function syncGeneralDraftsFromBackend() {
        root.draftTheme = root.safeString(backend.themeMode, "dark")
        root.draftLanguage = root.safeString(backend.language, "en")
        root.draftButtonSoundsMuted = backend.buttonSoundsMuted === true
        root.draftRunOnStartup = backend.runOnStartup === true
        root.draftRememberLoginEnabled = backend.rememberLoginEnabled === true
        root.generalDraftsReady = true
    }

    function clearGeneralFeedback() {
        if (!root.generalApplyInFlight)
            root.generalFeedbackText = ""
    }

    function chooseDraftTheme(mode) {
        root.draftTheme = mode
        root.clearGeneralFeedback()
    }

    function chooseDraftLanguage(code) {
        root.draftLanguage = code
        root.clearGeneralFeedback()
    }

    function setDraftButtonSoundsMuted(muted) {
        root.draftButtonSoundsMuted = muted
        root.clearGeneralFeedback()
    }

    function setDraftStartupEnabled(enabled) {
        root.draftRunOnStartup = enabled
        if (enabled)
            root.draftRememberLoginEnabled = true
        root.clearGeneralFeedback()
    }

    function setDraftRememberLoginEnabled(enabled) {
        root.draftRememberLoginEnabled = enabled
        if (!enabled)
            root.draftRunOnStartup = false
        root.clearGeneralFeedback()
    }

    function resetGeneralDrafts() {
        if (root.generalApplyInFlight)
            return
        root.syncGeneralDraftsFromBackend()
        root.generalFeedbackTone = "neutral"
        root.generalFeedbackText = root.label("تمت إعادة القيم إلى آخر حالة مؤكدة من النظام.", "Values were reset to the latest confirmed system state.")
    }

    function applyGeneralSettings() {
        if (root.settingsActionInFlight || root.generalApplyInFlight || !root.hasGeneralDraftChanges)
            return

        root.settingsActionInFlight = true
        root.generalApplyInFlight = true
        settingsGuardTimer.stop()
        root.pendingGeneralRequest = {
            "theme": root.draftTheme,
            "language": root.draftLanguage,
            "buttonSoundsMuted": root.draftButtonSoundsMuted,
            "runOnStartup": root.draftRunOnStartup,
            "rememberLoginEnabled": root.draftRememberLoginEnabled
        }
        root.generalFeedbackTone = "info"
        root.generalFeedbackText = root.label("جاري حفظ التغييرات…", "Applying changes…")

        if (root.draftTheme !== backend.themeMode)
            backend.setThemeMode(root.draftTheme)
        if (root.draftLanguage !== backend.language)
            backend.setLanguageCode(root.draftLanguage)
        if (root.draftButtonSoundsMuted !== backend.buttonSoundsMuted)
            backend.setButtonSoundsMuted(root.draftButtonSoundsMuted)
        if (root.draftRememberLoginEnabled !== backend.rememberLoginEnabled)
            backend.setRememberLoginEnabled(root.draftRememberLoginEnabled)
        if (root.draftRunOnStartup !== backend.runOnStartup)
            backend.setStartupEnabled(root.draftRunOnStartup)

        generalApplyFinishTimer.restart()
    }

    function finishGeneralApply() {
        if (!root.generalApplyInFlight)
            return

        var requested = root.pendingGeneralRequest || ({})
        var failed = false
        if (requested.theme !== undefined && requested.theme !== backend.themeMode)
            failed = true
        if (requested.language !== undefined && requested.language !== backend.language)
            failed = true
        if (requested.buttonSoundsMuted !== undefined && requested.buttonSoundsMuted !== backend.buttonSoundsMuted)
            failed = true
        if (requested.runOnStartup !== undefined && requested.runOnStartup !== backend.runOnStartup)
            failed = true
        if (requested.rememberLoginEnabled !== undefined && requested.rememberLoginEnabled !== backend.rememberLoginEnabled)
            failed = true

        root.syncGeneralDraftsFromBackend()
        root.pendingGeneralRequest = ({})
        root.generalApplyInFlight = false
        root.settingsActionInFlight = false

        if (failed) {
            root.generalFeedbackTone = "warn"
            root.generalFeedbackText = root.label("تعذر تطبيق بعض الإعدادات. تم تحديث الصفحة بالحالة المؤكدة من النظام.", "Some settings could not be applied. The page was refreshed with confirmed system state.")
        } else {
            root.generalFeedbackTone = "success"
            root.generalFeedbackText = root.label("تم تحديث الإعدادات حسب الحالة المؤكدة من النظام.", "Settings were updated according to confirmed system state.")
        }
    }

    function syncSecurityDraftsFromBackend() {
        root.draftAppPasscodeEnabled = backend.appPasscodeEnabled === true
        root.draftAppPasscodeTimeoutSec = Number(backend.appPasscodeTimeoutSec || 60)
        root.securityDraftsReady = true
    }

    function clearSecurityFeedback() {
        if (!root.securityApplyInFlight)
            root.securityFeedbackText = ""
    }

    function clearPasscodeDrafts() {
        if (root.currentPasscodeField)
            root.currentPasscodeField.text = ""
        if (root.newPasscodeField)
            root.newPasscodeField.text = ""
        if (root.confirmPasscodeField)
            root.confirmPasscodeField.text = ""
    }

    function setDraftAppPasscodeEnabled(enabled) {
        root.draftAppPasscodeEnabled = enabled
        root.clearSecurityFeedback()
    }

    function chooseDraftAppPasscodeTimeout(seconds) {
        if (root.securityApplyInFlight)
            return
        root.draftAppPasscodeTimeoutSec = Number(seconds || 60)
        root.clearSecurityFeedback()
    }

    function localPasscodeErrorText() {
        var currentText = root.currentPasscodeField ? String(root.currentPasscodeField.text || "") : ""
        var newText = root.newPasscodeField ? String(root.newPasscodeField.text || "") : ""
        var confirmText = root.confirmPasscodeField ? String(root.confirmPasscodeField.text || "") : ""
        var hasNewText = newText.length > 0 || confirmText.length > 0

        if (hasNewText && backend.appPasscodeConfigured === true && currentText.length === 0)
            return root.label("أدخل رمز الدخول الحالي قبل تغييره.", "Enter the current passcode before changing it.")
        if (root.draftAppPasscodeEnabled && backend.appPasscodeConfigured !== true && !hasNewText)
            return root.label("أنشئ رمز دخول جديد قبل تفعيل حماية رمز الدخول.", "Create a new passcode before enabling passcode protection.")
        if (!root.draftAppPasscodeEnabled && backend.appPasscodeEnabled === true && currentText.length === 0)
            return root.label("أدخل رمز الدخول الحالي لإيقاف الحماية.", "Enter the current passcode to turn protection off.")
        if (!root.draftAppPasscodeEnabled && hasNewText)
            return root.label("لا يمكن تغيير رمز الدخول وإيقافه في نفس العملية.", "You cannot change the passcode and turn it off in the same operation.")
        if (hasNewText) {
            if (newText.length < 4 || newText.length > 8)
                return root.label("رمز الدخول يجب أن يكون من 4 إلى 8 أرقام.", "Passcode must be 4 to 8 digits.")
            if (!/^[0-9]+$/.test(newText))
                return root.label("رمز الدخول يجب أن يحتوي على أرقام فقط.", "Passcode must contain digits only.")
            if (newText !== confirmText)
                return root.label("تأكيد رمز الدخول غير مطابق.", "Passcode confirmation does not match.")
        }
        return ""
    }

    function applySecuritySettings() {
        if (root.settingsActionInFlight || root.securityApplyInFlight || !root.hasSecurityDraftChanges)
            return

        var localError = root.localPasscodeErrorText()
        if (localError.length > 0) {
            root.securityFeedbackTone = "warn"
            root.securityFeedbackText = localError
            return
        }

        root.settingsActionInFlight = true
        root.securityApplyInFlight = true
        settingsGuardTimer.stop()
        root.pendingSecurityRequest = {
            "enabled": root.draftAppPasscodeEnabled,
            "timeoutSec": root.draftAppPasscodeTimeoutSec,
            "hadPasscodeText": root.hasSecurityPasscodeDraftText
        }
        root.securityFeedbackTone = "info"
        root.securityFeedbackText = root.label("جاري تحديث إعدادات الأمان…", "Updating security settings…")

        var currentText = root.currentPasscodeField ? String(root.currentPasscodeField.text || "") : ""
        var newText = root.newPasscodeField ? String(root.newPasscodeField.text || "") : ""
        var confirmText = root.confirmPasscodeField ? String(root.confirmPasscodeField.text || "") : ""

        if (newText.length > 0 || confirmText.length > 0) {
            backend.updateAppPasscode(currentText, newText, confirmText)
            root.clearPasscodeDrafts()
        }

        if (root.draftAppPasscodeTimeoutSec !== backend.appPasscodeTimeoutSec)
            backend.setAppPasscodeTimeoutSec(root.draftAppPasscodeTimeoutSec)

        if (root.draftAppPasscodeEnabled !== backend.appPasscodeEnabled) {
            if (root.draftAppPasscodeEnabled) {
                backend.setAppPasscodeEnabled(true)
            } else {
                var disabled = backend.disableAppPasscode(currentText)
                if (disabled)
                    root.clearPasscodeDrafts()
            }
        }

        securityApplyFinishTimer.restart()
    }

    function resetSecurityDrafts() {
        if (root.securityApplyInFlight)
            return
        root.syncSecurityDraftsFromBackend()
        root.clearPasscodeDrafts()
        root.securityFeedbackTone = "neutral"
        root.securityFeedbackText = root.label("تمت إعادة إعدادات الأمان إلى آخر حالة مؤكدة من النظام.", "Security settings were reset to the latest confirmed system state.")
    }

    function finishSecurityApply() {
        if (!root.securityApplyInFlight)
            return

        var requested = root.pendingSecurityRequest || ({})
        var failed = false
        if (requested.enabled !== undefined && requested.enabled !== backend.appPasscodeEnabled)
            failed = true
        if (requested.timeoutSec !== undefined && requested.timeoutSec !== backend.appPasscodeTimeoutSec)
            failed = true

        root.syncSecurityDraftsFromBackend()
        root.pendingSecurityRequest = ({})
        root.securityApplyInFlight = false
        root.settingsActionInFlight = false

        if (failed) {
            root.securityFeedbackTone = "warn"
            root.securityFeedbackText = root.label("تعذر تطبيق بعض إعدادات الأمان. تم تحديث الصفحة بالحالة المؤكدة من النظام.", "Some security settings could not be applied. The page was refreshed with confirmed system state.")
        } else if (requested.hadPasscodeText === true) {
            root.securityFeedbackTone = "info"
            root.securityFeedbackText = root.label("تم إرسال طلب تحديث رمز الدخول وتحديث الحالة المعروضة من النظام.", "The passcode update request was submitted and visible state was refreshed from the system.")
        } else {
            root.securityFeedbackTone = "success"
            root.securityFeedbackText = root.label("تم تحديث إعدادات الأمان حسب الحالة المؤكدة من النظام.", "Security settings were updated according to confirmed system state.")
        }
    }

    function clearAccountPasswordDrafts() {
        if (root.currentAccountPasswordField)
            root.currentAccountPasswordField.text = ""
        if (root.newAccountPasswordField)
            root.newAccountPasswordField.text = ""
        if (root.confirmAccountPasswordField)
            root.confirmAccountPasswordField.text = ""
    }

    function clearRecoveryPasswordDraft() {
        if (root.recoveryPasswordField)
            root.recoveryPasswordField.text = ""
    }

    function accountPasswordErrorText() {
        var currentText = root.currentAccountPasswordField ? String(root.currentAccountPasswordField.text || "") : ""
        var newText = root.newAccountPasswordField ? String(root.newAccountPasswordField.text || "") : ""
        var confirmText = root.confirmAccountPasswordField ? String(root.confirmAccountPasswordField.text || "") : ""

        if (currentText.length === 0)
            return root.label("أدخل كلمة المرور الحالية أولاً.", "Enter the current password first.")
        if (newText.length === 0)
            return root.label("أدخل كلمة المرور الجديدة.", "Enter the new password.")
        if (newText.length < 10)
            return root.label("كلمة المرور الجديدة يجب أن تكون 10 أحرف على الأقل.", "New password must be at least 10 characters.")
        if (!/[A-Za-z]/.test(newText) || !/[0-9]/.test(newText))
            return root.label("كلمة المرور الجديدة يجب أن تحتوي على حرف ورقم على الأقل.", "New password must include at least one letter and one number.")
        if (newText !== confirmText)
            return root.label("تأكيد كلمة المرور غير مطابق.", "Password confirmation does not match.")
        return ""
    }

    function updateAccountPassword() {
        if (root.settingsActionInFlight || root.accountSecurityActionInFlight)
            return

        var localError = root.accountPasswordErrorText()
        if (localError.length > 0) {
            root.accountSecurityFeedbackTone = "warn"
            root.accountSecurityFeedbackText = localError
            return
        }

        var currentText = root.currentAccountPasswordField ? String(root.currentAccountPasswordField.text || "") : ""
        var newText = root.newAccountPasswordField ? String(root.newAccountPasswordField.text || "") : ""

        root.settingsActionInFlight = true
        root.accountSecurityActionInFlight = true
        settingsGuardTimer.stop()
        root.accountSecurityFeedbackTone = "info"
        root.accountSecurityFeedbackText = root.label("تم إرسال طلب تحديث كلمة المرور للنظام.", "The password update request was sent to the system.")

        backend.changePassword(currentText, newText)
        root.clearAccountPasswordDrafts()
        accountSecurityActionGuardTimer.restart()
    }

    function regenerateAccountRecoveryCode() {
        if (root.settingsActionInFlight || root.accountSecurityActionInFlight)
            return

        var currentText = root.recoveryPasswordField ? String(root.recoveryPasswordField.text || "") : ""
        if (currentText.length === 0) {
            root.accountSecurityFeedbackTone = "warn"
            root.accountSecurityFeedbackText = root.label("أدخل كلمة المرور الحالية لإنشاء كود الاسترداد.", "Enter the current password to create a recovery code.")
            return
        }

        root.settingsActionInFlight = true
        root.accountSecurityActionInFlight = true
        settingsGuardTimer.stop()
        root.accountSecurityFeedbackTone = "info"
        root.accountSecurityFeedbackText = root.label("تم إرسال طلب كود الاسترداد. سيعرضه النظام مرة واحدة إذا نجح الطلب.", "Recovery code request sent. The system will show it once if the request succeeds.")

        backend.regeneratePasswordRecoveryCode(currentText)
        root.clearRecoveryPasswordDraft()
        accountSecurityActionGuardTimer.restart()
    }

    function finishAccountSecurityAction() {
        if (!root.accountSecurityActionInFlight)
            return
        root.accountSecurityActionInFlight = false
        if (!root.generalApplyInFlight && !root.securityApplyInFlight && !root.privacyApplyInFlight && !root.licenseActionInFlight && !root.updateActionInFlight && !root.deviceApplyInFlight && !root.deviceBenchmarkInFlight && !root.accountSecurityActionInFlight)
            root.settingsActionInFlight = false
    }

    function syncPrivacyDraftsFromBackend() {
        root.draftIncidentEvidenceEnabled = backend.incidentEvidenceEnabled === true
        root.draftIncidentEvidenceCaptureScreenshot = backend.incidentEvidenceCaptureScreenshot === true
        root.draftIncidentEvidenceCaptureWebcam = backend.incidentEvidenceCaptureWebcam === true
        root.draftIncidentEvidenceRetentionDays = Number(backend.incidentEvidenceRetentionDays || 30)
        root.privacyDraftsReady = true
    }

    function clearPrivacyFeedback() {
        if (!root.privacyApplyInFlight)
            root.privacyFeedbackText = ""
    }

    function setDraftIncidentEvidenceEnabled(enabled) {
        root.draftIncidentEvidenceEnabled = enabled
        root.clearPrivacyFeedback()
    }

    function setDraftIncidentEvidenceCaptureScreenshot(enabled) {
        root.draftIncidentEvidenceCaptureScreenshot = enabled
        root.clearPrivacyFeedback()
    }

    function setDraftIncidentEvidenceCaptureWebcam(enabled) {
        root.draftIncidentEvidenceCaptureWebcam = enabled
        root.clearPrivacyFeedback()
    }

    function chooseDraftIncidentEvidenceRetentionDays(days) {
        if (root.privacyApplyInFlight)
            return
        root.draftIncidentEvidenceRetentionDays = Number(days || 30)
        root.clearPrivacyFeedback()
    }

    function resetPrivacyDrafts() {
        if (root.privacyApplyInFlight)
            return
        root.syncPrivacyDraftsFromBackend()
        root.privacyFeedbackTone = "neutral"
        root.privacyFeedbackText = root.label("تمت إعادة إعدادات الخصوصية إلى آخر حالة مؤكدة من النظام.", "Privacy settings were reset to the latest confirmed system state.")
    }

    function applyPrivacySettings() {
        if (root.settingsActionInFlight || root.privacyApplyInFlight || !root.hasPrivacyDraftChanges)
            return

        root.settingsActionInFlight = true
        root.privacyApplyInFlight = true
        settingsGuardTimer.stop()
        root.pendingPrivacyRequest = {
            "enabled": root.draftIncidentEvidenceEnabled,
            "screenshot": root.draftIncidentEvidenceCaptureScreenshot,
            "webcam": root.draftIncidentEvidenceCaptureWebcam,
            "retentionDays": root.draftIncidentEvidenceRetentionDays
        }
        root.privacyFeedbackTone = "info"
        root.privacyFeedbackText = root.label("جاري حفظ إعدادات الخصوصية…", "Applying privacy settings…")

        if (root.draftIncidentEvidenceEnabled !== backend.incidentEvidenceEnabled)
            backend.setIncidentEvidenceEnabled(root.draftIncidentEvidenceEnabled)
        if (root.draftIncidentEvidenceCaptureScreenshot !== backend.incidentEvidenceCaptureScreenshot)
            backend.setIncidentEvidenceCaptureScreenshot(root.draftIncidentEvidenceCaptureScreenshot)
        if (root.draftIncidentEvidenceCaptureWebcam !== backend.incidentEvidenceCaptureWebcam)
            backend.setIncidentEvidenceCaptureWebcam(root.draftIncidentEvidenceCaptureWebcam)
        if (root.draftIncidentEvidenceRetentionDays !== backend.incidentEvidenceRetentionDays)
            backend.setIncidentEvidenceRetentionDays(root.draftIncidentEvidenceRetentionDays)

        privacyApplyFinishTimer.restart()
    }

    function finishPrivacyApply() {
        if (!root.privacyApplyInFlight)
            return

        var requested = root.pendingPrivacyRequest || ({})
        var failed = false
        if (requested.enabled !== undefined && requested.enabled !== backend.incidentEvidenceEnabled)
            failed = true
        if (requested.screenshot !== undefined && requested.screenshot !== backend.incidentEvidenceCaptureScreenshot)
            failed = true
        if (requested.webcam !== undefined && requested.webcam !== backend.incidentEvidenceCaptureWebcam)
            failed = true
        if (requested.retentionDays !== undefined && requested.retentionDays !== backend.incidentEvidenceRetentionDays)
            failed = true

        root.syncPrivacyDraftsFromBackend()
        root.pendingPrivacyRequest = ({})
        root.privacyApplyInFlight = false
        root.settingsActionInFlight = false

        if (failed) {
            root.privacyFeedbackTone = "warn"
            root.privacyFeedbackText = root.label("تعذر تطبيق بعض إعدادات الخصوصية. تم تحديث الصفحة بالحالة المؤكدة من النظام.", "Some privacy settings could not be applied. The page was refreshed with confirmed system state.")
        } else {
            root.privacyFeedbackTone = "success"
            root.privacyFeedbackText = root.label("تم تحديث إعدادات الخصوصية حسب الحالة المؤكدة من النظام.", "Privacy settings were updated according to confirmed system state.")
        }
    }

    function guardedExportSupportBundle() {
        if (root.settingsActionInFlight)
            return
        root.settingsActionInFlight = true
        settingsGuardTimer.restart()
        backend.exportSupportBundle()
    }

    function activateUserLicense() {
        if (root.settingsActionInFlight || root.licenseActionInFlight || !root.licenseCodeField)
            return
        var code = String(root.licenseCodeField.text || "").trim()
        if (code.length === 0) {
            root.licenseFeedbackTone = "warn"
            root.licenseFeedbackText = root.label("أدخل رمز الترخيص قبل التفعيل.", "Enter a license code before activation.")
            return
        }
        root.settingsActionInFlight = true
        root.licenseActionInFlight = true
        var result = backend.activateLicense(code)
        root.licenseCodeField.text = ""
        root.licenseFeedbackTone = result && result.ok ? "success" : "warn"
        root.licenseFeedbackText = root.safeString(result && result.message, root.label("تم إرسال طلب تفعيل الترخيص وتحديث الحالة من النظام.", "License activation was submitted and status was refreshed from the system."))
        licenseActionGuardTimer.restart()
    }

    function importUserLicenseFile() {
        if (root.settingsActionInFlight || root.licenseActionInFlight || !root.licensePathField)
            return
        var path = String(root.licensePathField.text || "").trim()
        if (path.length === 0) {
            root.licenseFeedbackTone = "warn"
            root.licenseFeedbackText = root.label("أدخل مسار ملف الترخيص قبل الاستيراد.", "Enter a license file path before importing.")
            return
        }
        root.settingsActionInFlight = true
        root.licenseActionInFlight = true
        var result = backend.importLicenseFile(path)
        root.licenseFeedbackTone = result && result.ok ? "success" : "warn"
        root.licenseFeedbackText = root.safeString(result && result.message, root.label("تم إرسال طلب استيراد الترخيص وتحديث الحالة من النظام.", "License import was submitted and status was refreshed from the system."))
        licenseActionGuardTimer.restart()
    }

    function refreshUserLicenseStatus() {
        if (root.settingsActionInFlight || root.licenseActionInFlight)
            return
        root.settingsActionInFlight = true
        root.licenseActionInFlight = true
        root.licenseFeedbackTone = "info"
        root.licenseFeedbackText = root.label("جاري تحديث حالة الترخيص…", "Refreshing license status…")
        backend.refreshLicenseStatus()
        licenseActionGuardTimer.restart()
    }

    function guardedCheckForUpdates() {
        if (root.settingsActionInFlight || root.updateOperationActive() || root.updateState.canCheck === false)
            return
        root.settingsActionInFlight = true
        root.updateActionInFlight = true
        root.updateFeedbackTone = "info"
        root.updateFeedbackText = root.label("جاري التحقق من التحديثات…", "Checking for updates…")
        backend.checkForUpdates()
        updateActionGuardTimer.restart()
    }

    function guardedDownloadUpdate() {
        if (root.settingsActionInFlight || root.updateOperationActive() || root.updateState.canDownload !== true)
            return
        root.settingsActionInFlight = true
        root.updateActionInFlight = true
        root.updateFeedbackTone = "info"
        root.updateFeedbackText = root.label("جاري تنزيل التحديث بعد موافقتك…", "Downloading the update after your approval…")
        backend.downloadAvailableUpdate()
        updateActionGuardTimer.restart()
    }

    function guardedInstallUpdate() {
        if (root.settingsActionInFlight || root.updateOperationActive() || root.updateState.canInstall !== true)
            return
        root.settingsActionInFlight = true
        root.updateActionInFlight = true
        root.updateFeedbackTone = "info"
        root.updateFeedbackText = root.label("جاري فتح مثبت التحديث المعتمد…", "Opening the verified update installer…")
        var opened = backend.openDownloadedUpdateInstaller()
        root.updateFeedbackTone = opened ? "success" : "warn"
        root.updateFeedbackText = opened ? root.label("تم فتح المثبت المعتمد. أكمل الخطوات من نافذة المثبت.", "The verified installer was opened. Continue in the installer window.") : root.label("تعذر فتح مثبت التحديث من الحالة الحالية.", "Could not open the update installer from the current state.")
        updateActionGuardTimer.restart()
    }


    function syncDeviceDraftsFromBackend() {
        root.draftDeepRuntimeMode = root.safeString(backend.deepRuntimeMode, "auto")
        root.deviceDraftsReady = true
    }

    function clearDeviceFeedback() {
        if (!root.deviceApplyInFlight && !root.deviceBenchmarkInFlight)
            root.deviceFeedbackText = ""
    }

    function chooseDraftDeepRuntimeMode(mode) {
        root.draftDeepRuntimeMode = root.safeString(mode, "auto")
        root.clearDeviceFeedback()
    }

    function useRecommendedDeviceMode() {
        if (!root.benchmarkReady || root.deviceApplyInFlight || root.deviceBenchmarkInFlight)
            return
        root.chooseDraftDeepRuntimeMode(root.safeString(backend.deepRuntimeRecommendedMode, "auto"))
        root.deviceFeedbackTone = "info"
        root.deviceFeedbackText = root.label("تم اختيار الوضع المقترح كمسودة. اضغط حفظ لتطبيقه.", "Recommended mode selected as a draft. Press Save to apply it.")
    }

    function resetDeviceDrafts() {
        if (root.deviceApplyInFlight || root.deviceBenchmarkInFlight)
            return
        root.syncDeviceDraftsFromBackend()
        root.deviceFeedbackTone = "neutral"
        root.deviceFeedbackText = root.label("تمت إعادة وضع الجهاز إلى آخر حالة مؤكدة من النظام.", "Device mode was reset to the latest confirmed system state.")
    }

    function applyDeviceSettings() {
        if (root.settingsActionInFlight || root.deviceApplyInFlight || root.deviceBenchmarkInFlight || !root.hasDeviceDraftChanges)
            return

        root.settingsActionInFlight = true
        root.deviceApplyInFlight = true
        settingsGuardTimer.stop()
        root.pendingDeviceRequest = {
            "deepRuntimeMode": root.draftDeepRuntimeMode,
            "action": "applyMode"
        }
        root.deviceFeedbackTone = "info"
        root.deviceFeedbackText = root.label("جاري حفظ وضع الجهاز…", "Applying device mode…")

        backend.setDeepRuntimeMode(root.draftDeepRuntimeMode)
        deviceApplyFinishTimer.restart()
    }

    function finishDeviceApply() {
        if (!root.deviceApplyInFlight)
            return

        var requested = root.pendingDeviceRequest || ({})
        var failed = requested.deepRuntimeMode !== undefined && requested.deepRuntimeMode !== root.safeString(backend.deepRuntimeMode, "auto")

        root.syncDeviceDraftsFromBackend()
        root.deviceApplyInFlight = false
        root.pendingDeviceRequest = ({})
        if (!root.generalApplyInFlight && !root.securityApplyInFlight && !root.privacyApplyInFlight && !root.licenseActionInFlight && !root.updateActionInFlight && !root.deviceBenchmarkInFlight && !root.accountSecurityActionInFlight)
            root.settingsActionInFlight = false

        if (failed) {
            root.deviceFeedbackTone = "danger"
            root.deviceFeedbackText = root.label("لم يؤكد النظام حفظ وضع الجهاز. راجع حالة النظام ثم حاول مرة أخرى.", "The system did not confirm the device mode. Check system status and try again.")
        } else {
            root.deviceFeedbackTone = "success"
            root.deviceFeedbackText = root.label("تم حفظ وضع الجهاز حسب الحالة المؤكدة من النظام.", "Device mode was saved according to confirmed system state.")
        }
    }

    function runUserDeviceBenchmark() {
        if (root.settingsActionInFlight || root.deviceBenchmarkInFlight || root.deviceApplyInFlight)
            return

        root.settingsActionInFlight = true
        root.deviceBenchmarkInFlight = true
        settingsGuardTimer.stop()
        root.pendingDeviceRequest = { "action": "runBenchmark" }
        root.deviceFeedbackTone = "info"
        root.deviceFeedbackText = root.label("جاري تشغيل فحص محلي للجهاز…", "Running a local device check…")

        backend.runDeepRuntimeBenchmark()
        deviceBenchmarkGuardTimer.restart()
    }

    function clearUserDeviceBenchmark() {
        if (root.settingsActionInFlight || root.deviceBenchmarkInFlight || root.deviceApplyInFlight || !root.benchmarkReady)
            return

        root.settingsActionInFlight = true
        root.deviceBenchmarkInFlight = true
        settingsGuardTimer.stop()
        root.pendingDeviceRequest = { "action": "clearBenchmark" }
        root.deviceFeedbackTone = "info"
        root.deviceFeedbackText = root.label("جاري مسح نتيجة فحص الجهاز…", "Clearing the saved device check…")

        backend.clearDeepRuntimeBenchmark()
        deviceBenchmarkGuardTimer.restart()
    }

    function finishDeviceBenchmark() {
        if (!root.deviceBenchmarkInFlight)
            return

        var action = root.pendingDeviceRequest ? root.pendingDeviceRequest.action : ""
        root.deviceBenchmarkInFlight = false
        root.pendingDeviceRequest = ({})
        root.syncDeviceDraftsFromBackend()
        if (!root.generalApplyInFlight && !root.securityApplyInFlight && !root.privacyApplyInFlight && !root.licenseActionInFlight && !root.updateActionInFlight && !root.deviceApplyInFlight && !root.accountSecurityActionInFlight)
            root.settingsActionInFlight = false

        if (action === "clearBenchmark") {
            root.deviceFeedbackTone = "success"
            root.deviceFeedbackText = root.label("تم مسح نتيجة فحص الجهاز المحفوظة.", "Saved device check was cleared.")
        } else if (root.benchmarkReady) {
            root.deviceFeedbackTone = "success"
            root.deviceFeedbackText = root.label("اكتمل فحص الجهاز. راجع الوضع المقترح ثم احفظه إذا أردت تطبيقه.", "Device check completed. Review the recommendation and save it if you want to apply it.")
        } else {
            root.deviceFeedbackTone = "warn"
            root.deviceFeedbackText = root.label("لم يؤكد النظام نتيجة فحص مكتملة بعد.", "The system has not confirmed a completed device check yet.")
        }
    }

    function openFaceSettingsPage() {
        if (root.rootWindow && root.rootWindow.navSelection !== undefined)
            root.rootWindow.navSelection = 3
    }

    function openPrivacySummary() {
        if (root.settingsActionInFlight)
            return
        root.settingsActionInFlight = true
        settingsGuardTimer.restart()
        backend.openPrivacyPolicy()
    }

    function openAboutUs() {
        if (root.settingsActionInFlight)
            return
        root.settingsActionInFlight = true
        settingsGuardTimer.restart()
        backend.openAboutUs()
    }

    function guardedToggleFaceEnrollmentFeature(enabled) {
        if (root.settingsActionInFlight)
            return
        root.settingsActionInFlight = true
        settingsGuardTimer.restart()
        backend.setFaceEnrollmentFeatureEnabled(enabled)
    }

    function guardedToggleFaceConfirmationFeature(enabled) {
        if (root.settingsActionInFlight)
            return
        root.settingsActionInFlight = true
        settingsGuardTimer.restart()
        backend.setFaceConfirmationFeatureEnabled(enabled)
    }

    function selectSection(sectionName) {
        root.activeSection = sectionName
    }

    function sectionTitle() {
        if (root.activeSection === "security")
            return root.label("الأمان", "Security")
        if (root.activeSection === "face")
            return root.label("الوجه والهوية", "Face & Identity")
        if (root.activeSection === "privacy")
            return root.label("الخصوصية", "Privacy")
        if (root.activeSection === "device")
            return root.label("ملاءمة الجهاز", "Device Fit")
        if (root.activeSection === "plan")
            return root.label("الخطة والتحديثات", "Plan & Updates")
        return root.label("عام", "General")
    }

    function sectionDescription() {
        if (root.activeSection === "security")
            return root.label("تحكم مبسط بحماية الدخول والجلسة، مع إبقاء قرارات الأمان داخل النظام.", "Simplified access and session controls while security decisions remain system-owned.")
        if (root.activeSection === "face")
            return root.label("إعدادات الوجه المعروضة هنا تعكس حالة النظام ولا تحسب نتيجة التحقق داخل الواجهة.", "Face settings shown here reflect system state and do not compute verification results in the UI.")
        if (root.activeSection === "privacy")
            return root.label("مركز واضح للخصوصية، الموافقة، والبيانات المحلية بدون عرض أي بيانات حساسة.", "A clear center for privacy, consent, and local data without exposing sensitive data.")
        if (root.activeSection === "device")
            return root.label("ملخص وضع التشغيل وملاءمة الجهاز بدون أدوات فنية متقدمة.", "A summary of operation mode and device fit without advanced technical tools.")
        if (root.activeSection === "plan")
            return root.label("إدارة الترخيص والتحديثات من الواجهة مع بقاء التحقق والتنزيل والتثبيت مملوكة للنظام.", "Manage license and updates from the app while verification, download, and install remain system-owned.")
        return root.label("إعدادات الاستخدام اليومية مثل المظهر، اللغة، التشغيل التلقائي، وتذكر تسجيل الدخول.", "Daily-use settings such as appearance, language, startup, and remembered login.")
    }

    function tabTone(sectionName) {
        return root.activeSection === sectionName ? "info" : "neutral"
    }

    Component.onCompleted: {
        root.syncGeneralDraftsFromBackend()
        root.syncSecurityDraftsFromBackend()
        root.syncPrivacyDraftsFromBackend()
        root.syncDeviceDraftsFromBackend()
    }

    Connections {
        target: backend
        function onThemeChanged() {
            if (root.generalApplyInFlight)
                generalApplyFinishTimer.restart()
            else
                root.syncGeneralDraftsFromBackend()
        }
        function onLanguageChanged() {
            if (root.generalApplyInFlight)
                generalApplyFinishTimer.restart()
            else
                root.syncGeneralDraftsFromBackend()
        }
        function onStartupChanged() {
            if (root.generalApplyInFlight)
                generalApplyFinishTimer.restart()
            else
                root.syncGeneralDraftsFromBackend()
        }
        function onRememberLoginChanged() {
            if (root.generalApplyInFlight)
                generalApplyFinishTimer.restart()
            else
                root.syncGeneralDraftsFromBackend()
        }
        function onButtonSoundsMutedChanged() {
            if (root.generalApplyInFlight)
                generalApplyFinishTimer.restart()
            else
                root.syncGeneralDraftsFromBackend()
        }
        function onAppPasscodeChanged() {
            if (root.securityApplyInFlight)
                securityApplyFinishTimer.restart()
            else
                root.syncSecurityDraftsFromBackend()
        }
        function onIncidentEvidenceChanged() {
            if (root.privacyApplyInFlight)
                privacyApplyFinishTimer.restart()
            else
                root.syncPrivacyDraftsFromBackend()
        }
        function onPrivacyCenterChanged() {
            if (!root.privacyApplyInFlight)
                root.syncPrivacyDraftsFromBackend()
        }
        function onLicenseChanged() {
            root.licenseActionInFlight = false
            if (!root.generalApplyInFlight && !root.securityApplyInFlight && !root.privacyApplyInFlight && !root.updateActionInFlight && !root.deviceApplyInFlight && !root.deviceBenchmarkInFlight && !root.accountSecurityActionInFlight)
                root.settingsActionInFlight = false
        }
        function onSupportBundleChanged() {
            if (!root.generalApplyInFlight && !root.securityApplyInFlight && !root.privacyApplyInFlight && !root.licenseActionInFlight && !root.updateActionInFlight && !root.deviceApplyInFlight && !root.deviceBenchmarkInFlight && !root.accountSecurityActionInFlight)
                root.settingsActionInFlight = false
        }
        function onUpdateStateChanged() {
            var state = String(root.updateState.state || "")
            if (state !== "checking" && state !== "downloading") {
                root.updateActionInFlight = false
                root.updateFeedbackTone = root.updateStateTone()
                root.updateFeedbackText = root.updateStateSummary()
                if (!root.generalApplyInFlight && !root.securityApplyInFlight && !root.privacyApplyInFlight && !root.licenseActionInFlight && !root.deviceApplyInFlight && !root.deviceBenchmarkInFlight && !root.accountSecurityActionInFlight)
                    root.settingsActionInFlight = false
            }
        }
        function onDeepRuntimeChanged() {
            if (root.deviceApplyInFlight)
                deviceApplyFinishTimer.restart()
            else if (root.deviceBenchmarkInFlight)
                deviceBenchmarkGuardTimer.restart()
            else
                root.syncDeviceDraftsFromBackend()
        }
        function onFaceConfirmationChanged() {
            if (!root.generalApplyInFlight && !root.securityApplyInFlight && !root.privacyApplyInFlight && !root.licenseActionInFlight && !root.updateActionInFlight && !root.deviceApplyInFlight && !root.deviceBenchmarkInFlight && !root.accountSecurityActionInFlight)
                root.settingsActionInFlight = false
        }
        function onStatusChanged() {
            if (root.securityApplyInFlight)
                securityApplyFinishTimer.restart()
            if (root.privacyApplyInFlight)
                privacyApplyFinishTimer.restart()
            if (!root.generalApplyInFlight && !root.securityApplyInFlight && !root.privacyApplyInFlight && !root.licenseActionInFlight && !root.updateActionInFlight && !root.deviceApplyInFlight && !root.deviceBenchmarkInFlight && !root.accountSecurityActionInFlight)
                root.settingsActionInFlight = false
        }
    }

    ColumnLayout {
        id: settingsContent
        width: Math.max(0, root.availableWidth)
        spacing: 18

        GlassCard {
            id: settingsHeroCard
            Layout.fillWidth: true
            implicitHeight: settingsHeroContent.implicitHeight + (root.denseLayout ? 32 : 44)
            Layout.minimumHeight: implicitHeight

            RowLayout {
                id: settingsHeroContent
                anchors.fill: parent
                anchors.margins: root.denseLayout ? 16 : 22
                spacing: root.denseLayout ? 14 : 22

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.preferredWidth: root.denseLayout ? settingsHeroCard.width : settingsHeroCard.width * 0.60
                    Layout.maximumWidth: root.denseLayout ? settingsHeroCard.width : settingsHeroCard.width * 0.64
                    spacing: 14

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        InfoPill {
                            textValue: root.label("العرض الحالي", "Current view") + ": " + root.label(backend.uiMode === "user" ? "الواجهة الأساسية" : "العرض المتقدم", backend.uiMode === "user" ? "Essential view" : "Advanced view")
                            pillTone: backend.uiMode === "user" ? "success" : "neutral"
                        }

                        InfoPill {
                            textValue: root.sectionTitle()
                            pillTone: root.tabTone(root.activeSection)
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.label("مركز الإعدادات", "Settings Center")
                        color: theme.text
                        font.pixelSize: root.denseLayout ? 28 : 34
                        font.bold: true
                        horizontalAlignment: root.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.sectionDescription()
                        color: theme.muted
                        font.pixelSize: 15
                        lineHeight: 1.14
                        horizontalAlignment: root.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 10

                        UserSettingsSectionChip {
                            theme: root.theme
                            textValue: root.label("عام", "General")
                            selected: root.activeSection === "general"
                            tone: root.tabTone("general")
                            chipHeight: root.sectionChipHeight
                            onChosen: root.selectSection("general")
                        }

                        UserSettingsSectionChip {
                            theme: root.theme
                            textValue: root.label("الأمان", "Security")
                            selected: root.activeSection === "security"
                            tone: root.tabTone("security")
                            chipHeight: root.sectionChipHeight
                            onChosen: root.selectSection("security")
                        }

                        UserSettingsSectionChip {
                            theme: root.theme
                            textValue: root.label("الوجه والهوية", "Face & Identity")
                            selected: root.activeSection === "face"
                            tone: root.tabTone("face")
                            chipHeight: root.sectionChipHeight
                            onChosen: root.selectSection("face")
                        }

                        UserSettingsSectionChip {
                            theme: root.theme
                            textValue: root.label("الخصوصية", "Privacy")
                            selected: root.activeSection === "privacy"
                            tone: root.tabTone("privacy")
                            chipHeight: root.sectionChipHeight
                            onChosen: root.selectSection("privacy")
                        }

                        UserSettingsSectionChip {
                            theme: root.theme
                            textValue: root.label("الجهاز", "Device Fit")
                            selected: root.activeSection === "device"
                            tone: root.tabTone("device")
                            chipHeight: root.sectionChipHeight
                            onChosen: root.selectSection("device")
                        }

                        UserSettingsSectionChip {
                            theme: root.theme
                            textValue: root.label("الخطة والتحديثات", "Plan & Updates")
                            selected: root.activeSection === "plan"
                            tone: root.tabTone("plan")
                            chipHeight: root.sectionChipHeight
                            onChosen: root.selectSection("plan")
                        }
                    }
                }

                HeroAssetFrame {
                    Layout.fillWidth: true
                    Layout.preferredWidth: settingsHeroCard.width * 0.36
                    Layout.preferredHeight: 260
                    visible: !root.denseLayout
                    sourceUrl: root.faceHero
                    tone: "success"
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

        UserGeneralSettingsSection {
            settingsRoot: root
        }

        UserSecuritySettingsSection {
            settingsRoot: root
        }

        UserFaceSettingsSection {
            settingsRoot: root
        }

        UserPrivacySettingsSection {
            settingsRoot: root
        }

        UserDeviceSettingsSection {
            settingsRoot: root
        }

        UserPlanSettingsSection {
            settingsRoot: root
        }
    }
}

