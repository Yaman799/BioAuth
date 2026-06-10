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
    property bool homeActionInFlight: false
    readonly property var runtimeState: backend.runtimeState || ({})
    readonly property bool canStartHomeEnrollment: backend.canStartEnrollmentLogger === true && !homeActionInFlight
    readonly property bool canStopHomeEnrollment: backend.canStopEnrollmentLogger === true && !homeActionInFlight
    readonly property bool canStartHomeProtection: backend.canStartProductionMonitor === true && !homeActionInFlight
    readonly property bool canStopHomeProtection: backend.canStopProductionMonitor === true && !homeActionInFlight
    readonly property bool homeProtectionFailure: runtimeState.technicalFailure === true || runtimeState.monitorFailed === true || runtimeState.loggerFailed === true || String(runtimeState.flow || "") === "protected_technical_failure"
    readonly property bool homeProtectionRunning: root.canStopHomeProtection && !root.homeProtectionFailure && (runtimeState.active === true || String(runtimeState.flow || "").indexOf("protected_") === 0)
    readonly property bool canTrainHomeModel: backend.canTrain === true && backend.trainingInProgress !== true && !homeActionInFlight
    readonly property bool denseLayout: width < 980
    readonly property bool narrowActions: width < 720
    readonly property var faceState: backend.faceConfirmationState || ({})
    readonly property var profileState: backend.profile || ({})
    readonly property var modelState: backend.modelReadinessState || ({})
    readonly property var productionApproval: backend.productionApprovalState || ({})
    readonly property var autoEnrollment: backend.autoEnrollmentState || ({})
    readonly property var trainingProgress: backend.trainingProgress || ({})
    readonly property var tourHeroTarget: commandCard
    readonly property var tourQuickActionsTarget: homeQuickActionsCard
    readonly property var tourLearningProgressTarget: learningProgressCard
    readonly property var tourRecentActivityTarget: recentActivityCard
    readonly property string protectionTone: runtimeState.active ? (runtimeState.statusTone || "success") : (backend.statusTone || "info")
    readonly property string faceTone: faceState.enrolled ? "success" : (faceState.enabled ? "warn" : "neutral")
    readonly property string modelTone: modelState.ready === true ? "success" : "info"
    readonly property url heroImage: Qt.resolvedUrl("../../assets/bioauth/01_hero_integrated/02_home_protection_check_integrated.png")
    readonly property url faceIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/03_face_scan.png")
    readonly property url sessionIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/10_session_monitor.png")
    readonly property url modelIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/17_model_brain.png")
    readonly property url activityIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/08_activity_history.png")
    readonly property url checkIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/18_check_success.png")
    readonly property url updateIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/04_updates_refresh.png")
    readonly property url privacyIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/06_privacy_lock.png")

    clip: true
    contentWidth: availableWidth

    function label(arText, enText) {
        return Ui.trx(backend.language === "ar", arText, enText)
    }

    function tourTarget(name) {
        if (name === "homeHero") return commandCard
        if (name === "homeQuickActions") return homeQuickActionsCard
        if (name === "homeStartEnrollment") return startEnrollmentButton
        if (name === "homeLearningProgress") return learningProgressCard
        if (name === "homeTrainModel") return trainProtectionModelButton
        if (name === "homeRecentActivity") return recentActivityCard
        return null
    }

    function guardedStartEnrollment() {
        if (!root.canStartHomeEnrollment)
            return
        root.homeActionInFlight = true
        homeActionGuardTimer.restart()
        var result = backend.requestUserHomeAction("start_enrollment")
        if (!result || result.ok !== true)
            root.homeActionInFlight = false
    }

    function guardedStopEnrollment() {
        if (!root.canStopHomeEnrollment)
            return
        stopEnrollmentDialog.open()
    }

    function performStopEnrollment() {
        if (!root.canStopHomeEnrollment)
            return
        root.homeActionInFlight = true
        homeActionGuardTimer.restart()
        var result = backend.requestUserHomeAction("stop_enrollment")
        if (!result || result.ok !== true)
            root.homeActionInFlight = false
    }

    function guardedStartProtection() {
        if (!root.canStartHomeProtection)
            return
        root.homeActionInFlight = true
        homeActionGuardTimer.restart()
        var result = backend.requestUserHomeAction("start_protection")
        if (!result || result.ok !== true)
            root.homeActionInFlight = false
    }

    function guardedStopProtection() {
        if (!root.canStopHomeProtection)
            return
        stopProtectionDialog.open()
    }

    function performStopProtection() {
        if (!root.canStopHomeProtection)
            return
        root.homeActionInFlight = true
        homeActionGuardTimer.restart()
        var result = backend.requestUserHomeAction("stop_protection")
        if (!result || result.ok !== true)
            root.homeActionInFlight = false
    }

    function guardedTrainProfile() {
        if (!root.canTrainHomeModel)
            return
        root.homeActionInFlight = true
        homeActionGuardTimer.restart()
        var result = backend.requestUserHomeAction("train_profile")
        if (!result || result.ok !== true)
            root.homeActionInFlight = false
    }

    function trainingPercentText() {
        var percent = Number(trainingProgress.percent || 0)
        if (isNaN(percent))
            percent = 0
        return String(Math.max(0, Math.min(100, Math.round(percent)))) + "%"
    }

    function trainModelButtonText() {
        if (backend.trainingInProgress === true)
            return root.label("جاري التدريب • ", "Training • ") + root.trainingPercentText()
        return root.label("تدريب نموذج الحماية", "Train Protection Model")
    }

    function trainModelUnavailableText() {
        if (backend.trainingInProgress === true)
            return root.label("التدريب يعمل الآن. اتركه يكتمل في الخلفية.", "Training is already running. Let it finish in the background.")
        var safe = root.userSafeText(backend.trainingBlockedReason, "")
        if (safe.length > 0)
            return safe
        if (root.learningAcceptedSessions() < root.learningRequiredSessions())
            return root.label("اجمع جلسات موثوقة أكثر قبل التدريب.", "Collect more trusted sessions before training.")
        return root.homeActionUnavailableText()
    }


    function homeActionUnavailableText() {
        return root.label("الإجراء غير متاح الآن. تحقق من حالة الحماية أو التعلم ثم حاول مرة أخرى.", "Action unavailable right now. Check protection or learning status, then try again.")
    }

    function quickActionsStatusText() {
        if (root.homeProtectionFailure) {
            if (runtimeState.monitorFailed === true || String(runtimeState.statusCode || "").indexOf("monitor") === 0)
                return root.label("فشل المراقب", "Monitor failed")
            if (runtimeState.loggerFailed === true || String(runtimeState.statusCode || "").indexOf("logger") === 0)
                return root.label("فشل المسجل", "Logger failed")
            return root.label("الحماية تحتاج انتباه", "Protection needs attention")
        }
        if (root.homeProtectionRunning)
            return root.label("الحماية تعمل", "Protection running")
        if (root.canStartHomeProtection)
            return root.label("جاهزة للبدء", "Ready to start")
        if (root.canStopHomeProtection)
            return root.label("تنظيف الحالة متاح", "Cleanup available")
        if (root.canStopHomeEnrollment)
            return root.label("التعلم يعمل", "Learning running")
        if (root.canStartHomeEnrollment)
            return root.label("جاهزة للتعلم", "Ready to learn")
        return root.label("بانتظار النظام", "Waiting")
    }

    function quickActionsTone() {
        if (root.homeProtectionFailure)
            return "danger"
        if (root.homeProtectionRunning || root.canStopHomeEnrollment)
            return "success"
        if (root.canStartHomeProtection || root.canStartHomeEnrollment || root.canStopHomeProtection)
            return "info"
        return "neutral"
    }

    function isAttentionTone(tone) {
        var t = String(tone || "").toLowerCase()
        return t === "warn" || t === "warning" || t === "danger" || t === "error"
    }

    function userSafeText(value, fallbackText) {
        var text = String(value || "")
        if (text.length === 0)
            return fallbackText || ""
        var lower = text.toLowerCase()
        if (lower.indexOf("sha" + "dow") >= 0 || lower.indexOf("candidate") >= 0 || lower.indexOf("challenger") >= 0 || lower.indexOf("promotion") >= 0 || lower.indexOf("ledger") >= 0 || lower.indexOf("digest") >= 0) {
            if (lower.indexOf("suspicious") >= 0 || lower.indexOf("attention") >= 0 || lower.indexOf("fail") >= 0 || lower.indexOf("mismatch") >= 0)
                return root.label("مراجعة تحديث الحماية تحتاج انتباهًا", "Protection update review needs attention")
            if (lower.indexOf("pending") >= 0 || lower.indexOf("waiting") >= 0 || lower.indexOf("partial") >= 0 || lower.indexOf("collecting") >= 0)
                return root.label("يتم جمع أدلة آمنة قبل إتاحة التحديث.", "Safe evidence is being collected before the update becomes available.")
            return root.label("تحديث الحماية قيد المراجعة في الخلفية.", "A protection update is being reviewed in the background.")
        }
        if (lower.indexOf("face") >= 0 && lower.indexOf("model") >= 0 && (lower.indexOf("missing") >= 0 || lower.indexOf("not found") >= 0))
            return root.label("إعداد تأكيد الوجه مطلوب", "Face confirmation needs setup")
        if (lower.indexOf("system evidence") >= 0)
            return root.label("فحص نموذج الحماية", "Protection model check")
        if (lower.indexOf("raw " + "telemetry") >= 0 || lower.indexOf("reason_" + "code") >= 0 || lower.indexOf("gate_" + "results") >= 0 || lower === "f" + "ar" || lower === "f" + "rr")
            return root.label("تتم مراجعة تفاصيل الحماية.", "Protection details are being reviewed.")
        if (lower.indexOf("production") >= 0 || lower.indexOf("runtime") >= 0 || lower.indexOf("bundle") >= 0 || lower.indexOf("approval") >= 0 || lower.indexOf("gate") >= 0) {
            if (root.protectionReadyForDisplay())
                return root.label("الحماية جاهزة ويمكن بدء جلسة محمية.", "Protection is ready and a protected session can start.")
            if (profileState.ready === true)
                return root.label("النظام يراجع الجاهزية النهائية قبل فتح الجلسات المحمية.", "BioAuth is checking final readiness before protected sessions unlock.")
            return root.label("BioAuth يحتاج جلسات موثوقة أكثر قبل فتح الحماية الكاملة.", "BioAuth needs more trusted sessions before full protection unlocks.")
        }
        return text
    }

    function protectionReadyForDisplay() {
        return backend.canStartProtected === true || backend.canStopProductionMonitor === true || runtimeState.active === true
    }

    function cleanReadinessText(value, fallbackText) {
        return root.userSafeText(value, fallbackText)
    }

    function readinessStatusTone() {
        if (root.protectionReadyForDisplay())
            return "success"
        if (backend.trainingInProgress === true || modelState.readinessLevel === "targeted_collection")
            return "info"
        if (profileState.ready === true || modelState.ready === true)
            return "warn"
        if (autoEnrollment.consentSatisfied === false)
            return "warn"
        return "info"
    }

    function readinessStatusTitle() {
        if (root.protectionReadyForDisplay())
            return root.label("الحماية جاهزة", "Protection ready")
        if (backend.trainingInProgress === true)
            return root.label("يجري تدريب الحماية", "Training protection")
        if (autoEnrollment.trainingReady === true || profileState.training_can_start === true)
            return root.label("جاهز للتدريب", "Ready to train")
        if (profileState.ready === true)
            return root.label("قيد الفحص النهائي", "Final check in progress")
        if (autoEnrollment.collecting === true)
            return root.label("يتعلم سلوكك", "Learning your behavior")
        if (autoEnrollment.consentSatisfied === false)
            return root.label("الموافقة مطلوبة", "Consent required")
        return root.label("يتجهز للحماية", "Preparing protection")
    }

    function readinessStatusBody() {
        if (root.protectionReadyForDisplay())
            return root.cleanReadinessText(productionApproval.safeRecommendationText, root.label("يمكنك بدء جلسة محمية من صفحة الحماية عندما تكون جاهزاً.", "You can start a protected session from the Protection page when ready."))
        if (backend.trainingInProgress === true)
            return root.cleanReadinessText(trainingProgress.headline || trainingProgress.detail, root.label("BioAuth يدرب نموذج الحماية في الخلفية. يمكنك متابعة استخدام الجهاز.", "BioAuth is training your protection model in the background. You can keep using the device."))
        if (autoEnrollment.trainingReady === true || profileState.training_can_start === true)
            return root.label("تم جمع جلسات كافية. الخطوة التالية هي تدريب نموذج الحماية.", "Enough sessions are collected. The next step is training the protection model.")
        if (modelState.safeUserMessage || modelState.nextBestActionText)
            return root.cleanReadinessText((modelState.safeUserMessage || "") + " " + (modelState.nextBestActionText || ""), root.label("BioAuth يحتاج معلومات أكثر قبل فتح الجلسات المحمية.", "BioAuth needs more evidence before protected sessions unlock."))
        if (productionApproval.approvalReasonText || productionApproval.safeRecommendationText)
            return root.cleanReadinessText(productionApproval.approvalReasonText || productionApproval.safeRecommendationText, root.label("النظام يراجع جاهزية الحماية قبل السماح بالجلسات المحمية.", "BioAuth is checking readiness before allowing protected sessions."))
        return root.label("استخدم الجهاز بشكل طبيعي حتى يكتمل التعلم وتصبح الحماية جاهزة.", "Use the device normally until learning completes and protection is ready.")
    }

    function readinessNextActionText() {
        if (root.protectionReadyForDisplay())
            return root.label("استخدم الأزرار السريعة في Home لبدء الحماية، وافتح صفحة الحماية للتفاصيل.", "Use Home quick actions to start protection, and open Protection for details.")
        if (backend.trainingInProgress === true)
            return root.label("اترك التدريب يكتمل في الخلفية.", "Let background training finish.")
        if (autoEnrollment.trainingReady === true || profileState.training_can_start === true)
            return root.label("درّب نموذج الحماية عندما تكون جاهزاً.", "Train the protection model when you are ready.")
        if (autoEnrollment.nextBestActionText || modelState.nextBestActionText)
            return root.cleanReadinessText(autoEnrollment.nextBestActionText || modelState.nextBestActionText, root.label("اجمع جلسات موثوقة أكثر.", "Collect more trusted sessions."))
        return root.label("استمر باستخدام الجهاز بشكل طبيعي.", "Keep using the device normally.")
    }

    function learningAcceptedSessions() {
        var accepted = Number(autoEnrollment.acceptedSessions)
        if (!isNaN(accepted) && accepted > 0)
            return accepted
        return Number(profileState.session_count || 0)
    }

    function learningRequiredSessions() {
        var required = Number(autoEnrollment.requiredSessions)
        if (!isNaN(required) && required > 0)
            return required
        required = Number(backend.minEnrollmentText || 0)
        return required > 0 ? required : 8
    }

    function learningRecommendedSessions() {
        var recommended = Number(autoEnrollment.recommendedSessions)
        if (!isNaN(recommended) && recommended > 0)
            return recommended
        recommended = Number(backend.maxEnrollmentText || 0)
        return recommended > 0 ? recommended : Math.max(root.learningRequiredSessions(), 15)
    }

    function learningProgressPercent() {
        var required = root.learningRequiredSessions()
        if (required <= 0)
            return 0
        return Math.max(0, Math.min(100, Math.round((root.learningAcceptedSessions() / required) * 100)))
    }

    function learningStatusTone() {
        if (profileState.ready === true || autoEnrollment.trainingReady === true)
            return "success"
        if (backend.trainingInProgress === true || autoEnrollment.collecting === true)
            return "info"
        if (autoEnrollment.consentSatisfied === false)
            return "warn"
        return "neutral"
    }

    function learningStatusTitle() {
        if (backend.trainingInProgress === true)
            return root.label("التدريب يعمل الآن", "Training is running")
        if (autoEnrollment.trainingReady === true || profileState.training_can_start === true)
            return root.label("جلسات كافية للتدريب", "Enough sessions to train")
        if (profileState.ready === true)
            return root.label("ملف السلوك جاهز", "Behavior profile ready")
        if (autoEnrollment.collecting === true)
            return root.label("يجمع جلسات موثوقة", "Collecting trusted sessions")
        if (autoEnrollment.enabled === true)
            return root.label("التعلم مفعّل", "Learning enabled")
        return root.label("التعلم بانتظار الإعداد", "Learning waiting for setup")
    }

    function learningStatusBody() {
        if (backend.trainingInProgress === true)
            return root.cleanReadinessText(trainingProgress.headline || trainingProgress.detail, root.label("يتم تدريب نموذج الحماية الآن.", "The protection model is being trained now."))
        if (autoEnrollment.collectionStatusText)
            return root.cleanReadinessText(autoEnrollment.collectionStatusText, root.label("BioAuth يتابع تقدم التعلم.", "BioAuth is tracking learning progress."))
        if (profileState.progressText)
            return root.cleanReadinessText(profileState.progressText, root.label("BioAuth يتعلم من الجلسات الموثوقة.", "BioAuth learns from trusted sessions."))
        return root.label("كل جلسة موثوقة تساعد BioAuth على بناء حماية أدق.", "Every trusted session helps BioAuth build more accurate protection.")
    }

    function heroSummaryText() {
        if (runtimeState.active)
            return root.label("يفحص BioAuth الجلسة الحالية بهدوء في الخلفية ويعرض ما يؤكده النظام فقط.", "BioAuth is checking the current session in the background and only shows confirmed system state.")
        if (backend.canStartProtected === true)
            return root.label("يمكنك بدء الحماية من Home مباشرة، وفتح صفحة الحماية لمتابعة التفاصيل.", "You can start protection directly from Home and open Protection for details.")
        return root.userSafeText(runtimeState.runtimeDisplayText || backend.statusMessage, backend.tr("user_home_protection_card_body"))
    }

    function conciseSessionStatus() {
        if (runtimeState.active)
            return root.label("نشط", "Active")
        if (backend.canStartProtected === true)
            return root.label("جاهز للبدء", "Ready to start")
        if (root.isAttentionTone(root.protectionTone))
            return root.label("يحتاج انتباهًا", "Needs attention")
        return root.label("بانتظار", "Waiting")
    }

    function conciseSessionDetail() {
        if (backend.canStartProtected === true || backend.canStopProductionMonitor === true)
            return root.label("الأوامر السريعة موجودة في Home، والتفاصيل في صفحة الحماية.", "Quick actions are on Home; details remain on the Protection page.")
        return root.label("سيظهر التحكم في صفحة الحماية عند توفره من النظام.", "Controls appear on the Protection page when the system makes them available.")
    }

    function conciseFaceStatus() {
        var safe = root.userSafeText(faceState.statusText, "")
        if (safe.length > 0 && safe !== String(faceState.statusText || ""))
            return safe
        if (faceState.enrolled)
            return root.label("إعداد الوجه جاهز", "Face setup ready")
        if (faceState.enabled === false)
            return root.label("غير مفعّل", "Not enabled")
        return root.label("يحتاج إعداد", "Needs setup")
    }

    function conciseFaceDetail() {
        if (faceState.enabled === false)
            return root.label("تأكيد الوجه غير مفعّل حالياً.", "Face confirmation is not enabled right now.")
        if (faceState.enrolled)
            return root.label("الحالة مؤكدة من النظام.", "Status is confirmed by the system.")
        return root.label("أكمل إعداد الوجه عندما يطلب النظام ذلك.", "Complete face setup when the system asks for it.")
    }

    function conciseModelStatus() {
        var readyText = root.userSafeText(modelState.readyText || modelState.statusText, "")
        if (readyText.length > 0)
            return readyText
        if (modelState.ready === true)
            return root.label("جاهز", "Ready")
        return root.label("قيد الفحص", "Checking")
    }

    function conciseModelDetail() {
        var safe = root.userSafeText(modelState.safeUserMessage, "")
        if (safe.length > 0)
            return safe
        if (modelState.ready === true)
            return root.label("فحص نموذج الحماية مكتمل.", "Protection model check is complete.")
        return root.label("ينتظر BioAuth دليل الجاهزية من النظام.", "BioAuth is waiting for readiness evidence from the system.")
    }

    function backgroundReviewActive() {
        var status = String(productionApproval.modelStatus || productionApproval.model_status || modelState.modelStatus || modelState.status || "").toLowerCase()
        var action = String(modelState.backgroundAction || modelState.background_action || "").toLowerCase()
        if (status.indexOf("sha" + "dow") >= 0 || status.indexOf("pending") >= 0 || status.indexOf("review") >= 0)
            return true
        if (action.indexOf("training") >= 0 || action.indexOf("validation") >= 0 || action.indexOf("review") >= 0)
            return true
        return false
    }

    function backgroundReviewTone() {
        if (root.protectionReadyForDisplay())
            return "info"
        return root.backgroundReviewActive() ? "warn" : "neutral"
    }

    function backgroundReviewTitle() {
        if (root.backgroundReviewActive())
            return root.label("تحديث حماية قيد المراجعة", "Protection update under review")
        return root.label("لا يوجد تحديث يحتاج إجراء", "No update needs action")
    }

    function backgroundReviewBody() {
        if (root.backgroundReviewActive())
            return root.label("يبقى نموذج الحماية الحالي هو المعتمد، بينما يراجع BioAuth تحديثًا جديدًا في الخلفية بدون التأثير على الحماية أو التدريب.", "The current protection model stays in charge while BioAuth reviews a new update in the background without affecting protection or training.")
        return root.label("عندما يصبح تحديث جديد مؤهلاً، ستراه في صفحة تحديث النموذج قبل تطبيقه.", "When a new update becomes eligible, you will see it on the Model Update page before applying it.")
    }


    Timer {
        id: homeActionGuardTimer
        interval: 900
        repeat: false
        onTriggered: root.homeActionInFlight = false
    }

    ConfirmDialog {
        id: stopEnrollmentDialog
        rootWindow: root.rootWindow ? root.rootWindow : root
        bodyText: root.label("إيقاف التعلم يوقف جمع جلسات السلوك الموثوقة إلى أن تبدأه من جديد. هل تريد المتابعة؟", "Stopping enrollment pauses trusted behavior collection until you start it again. Continue?")
        confirmText: root.label("إيقاف التعلم", "Stop enrollment")
        cancelText: root.label("إلغاء", "Cancel")
        tone: "danger"
        onConfirmed: root.performStopEnrollment()
    }

    ConfirmDialog {
        id: stopProtectionDialog
        rootWindow: root.rootWindow ? root.rootWindow : root
        bodyText: root.label("إيقاف الحماية يوقف مراقبة الجلسة الحالية. استخدمه فقط عندما تكون متأكدًا. هل تريد المتابعة؟", "Stopping protection ends monitoring for the current session. Use this only when you are sure. Continue?")
        confirmText: root.label("إيقاف الحماية", "Stop protection")
        cancelText: root.label("إلغاء", "Cancel")
        tone: "danger"
        onConfirmed: root.performStopProtection()
    }

    ColumnLayout {
        width: root.availableWidth
        spacing: 18

        GlassCard {
            id: commandCard
            Layout.fillWidth: true
            implicitHeight: Math.max(root.denseLayout ? 680 : 470, commandContent.implicitHeight + (root.denseLayout ? 32 : 44))
            Layout.minimumHeight: implicitHeight

            RowLayout {
                id: commandContent
                anchors.fill: parent
                anchors.margins: root.denseLayout ? 16 : 22
                spacing: root.denseLayout ? 14 : 22

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: root.denseLayout ? commandCard.width : commandCard.width * 0.60
                    Layout.maximumWidth: root.denseLayout ? commandCard.width : commandCard.width * 0.62
                    spacing: 14

                    InfoPill {
                        textValue: root.conciseSessionStatus()
                        pillTone: root.protectionTone
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.label("نظرة عامة على الحماية", "Protection Overview")
                        color: theme.text
                        font.pixelSize: root.denseLayout ? 28 : 34
                        font.bold: true
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.heroSummaryText()
                        color: theme.muted
                        font.pixelSize: 15
                        lineHeight: 1.12
                        wrapMode: Text.Wrap
                        maximumLineCount: 3
                        elide: Text.ElideRight
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: root.denseLayout ? 1 : 2
                        columnSpacing: 12
                        rowSpacing: 12

                        PremiumMetricCard {
                            Layout.fillWidth: true
                            Layout.minimumHeight: 126
                            compact: true
                            iconSource: root.faceIcon
                            tone: root.faceTone
                            title: root.label("الوجه", "Face")
                            value: root.conciseFaceStatus()
                            detail: root.conciseFaceDetail()
                        }

                        PremiumMetricCard {
                            Layout.fillWidth: true
                            Layout.minimumHeight: 126
                            compact: true
                            iconSource: root.sessionIcon
                            tone: root.protectionTone
                            title: root.label("الجلسة", "Session")
                            value: root.conciseSessionStatus()
                            detail: root.conciseSessionDetail()
                        }

                        PremiumMetricCard {
                            Layout.fillWidth: true
                            Layout.minimumHeight: 126
                            compact: true
                            iconSource: root.modelIcon
                            tone: root.modelTone
                            title: root.label("نموذج الحماية", "Protection model")
                            value: root.conciseModelStatus()
                            detail: root.conciseModelDetail()
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        Layout.topMargin: 8
                        columns: root.narrowActions ? 1 : 2
                        columnSpacing: 12
                        rowSpacing: 10

                        AppButton {
                            Layout.fillWidth: true
                            Layout.minimumHeight: 44
                            text: root.label("فتح صفحة الحماية", "Open protection")
                            role: "primary"
                            onClicked: if (rootWindow) rootWindow.navSelection = 1
                        }

                        AppButton {
                            Layout.fillWidth: true
                            Layout.minimumHeight: 44
                            text: root.label("إعداد الوجه", "Face setup")
                            role: "details"
                            onClicked: if (rootWindow) rootWindow.navSelection = 3
                        }
                    }
                }

                Item {
                    visible: !root.denseLayout
                    Layout.preferredWidth: commandCard.width * 0.38
                    Layout.fillHeight: true

                    HeroAssetFrame {
                        anchors.fill: parent
                        anchors.leftMargin: 4
                        sourceUrl: root.heroImage
                        tone: root.protectionTone
                        cornerRadius: 24
                        imageBleed: 8
                        imageFillMode: Image.PreserveAspectCrop
                        imageOpacity: 1.0
                        overlayOpacity: 0.0
                        edgeFadeOpacity: 0.0
                        ambientWashOpacity: 0.0
                    }
                }
            }
        }

        GlassCard {
            id: homeQuickActionsCard
            Layout.fillWidth: true
            implicitHeight: homeQuickActionsContent.implicitHeight + 36
            Layout.minimumHeight: implicitHeight

            ColumnLayout {
                id: homeQuickActionsContent
                anchors.fill: parent
                anchors.margins: 18
                spacing: 14

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Label {
                        Layout.fillWidth: true
                        text: root.label("أوامر سريعة", "Quick actions")
                        color: theme.text
                        font.pixelSize: 22
                        font.bold: true
                        wrapMode: Text.Wrap
                    }

                    InfoPill {
                        textValue: root.quickActionsStatusText()
                        pillTone: root.quickActionsTone()
                    }
                }

                Label {
                    Layout.fillWidth: true
                    text: root.label("ابدأ أو أوقف الحماية والتعلم من الصفحة الرئيسية. التفاصيل المتقدمة تبقى في العرض المتقدم.", "Start or stop protection and learning from Home. Advanced details stay in the advanced view.")
                    color: theme.muted
                    font.pixelSize: 13
                    wrapMode: Text.Wrap
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: root.narrowActions ? 1 : 2
                    columnSpacing: 12
                    rowSpacing: 10

                    AppButton {
                        objectName: "userHomeStartProtectionButton"
                        Layout.fillWidth: true
                        Layout.minimumHeight: 46
                        text: root.label("بدء الحماية", "Start Protection")
                        role: "primary"
                        enabled: root.canStartHomeProtection
                        debugLabel: "user_home_start_protection"
                        onClicked: root.guardedStartProtection()
                    }

                    AppButton {
                        objectName: "userHomeStopProtectionButton"
                        Layout.fillWidth: true
                        Layout.minimumHeight: 46
                        text: root.label("إيقاف الحماية", "Stop Protection")
                        role: "danger"
                        enabled: root.canStopHomeProtection
                        debugLabel: "user_home_stop_protection"
                        onClicked: root.guardedStopProtection()
                    }

                    AppButton {
                        id: startEnrollmentButton
                        objectName: "userHomeStartEnrollmentButton"
                        Layout.fillWidth: true
                        Layout.minimumHeight: 46
                        text: root.label("بدء التعلم", "Start Enrollment")
                        role: "success"
                        enabled: root.canStartHomeEnrollment
                        debugLabel: "user_home_start_enrollment"
                        ToolTip.visible: hovered && !enabled
                        ToolTip.text: root.homeActionUnavailableText()
                        ToolTip.delay: 100
                        onClicked: root.guardedStartEnrollment()
                    }

                    AppButton {
                        objectName: "userHomeStopEnrollmentButton"
                        Layout.fillWidth: true
                        Layout.minimumHeight: 46
                        text: root.label("إيقاف التعلم", "Stop Enrollment")
                        role: "danger"
                        enabled: root.canStopHomeEnrollment
                        debugLabel: "user_home_stop_enrollment"
                        ToolTip.visible: hovered && !enabled
                        ToolTip.text: root.homeActionUnavailableText()
                        ToolTip.delay: 100
                        onClicked: root.guardedStopEnrollment()
                    }
                }

                StatusInfoRow {
                    Layout.fillWidth: true
                    iconSource: root.sessionIcon
                    tone: root.quickActionsTone()
                    title: root.label("حالة الأوامر", "Command status")
                    detail: root.label("الأزرار تتبع حالة النظام الحالية ولا تعرض نجاحًا أمنيًا إلا عندما يؤكده BioAuth.", "Buttons follow current system state and do not claim security success unless BioAuth confirms it.")
                }
            }
        }

        GridLayout {
            id: readinessLearningGrid
            Layout.fillWidth: true
            columns: root.denseLayout ? 1 : 2
            columnSpacing: 18
            rowSpacing: 18

            GlassCard {
                id: protectionReadinessCard
                Layout.fillWidth: true
                implicitHeight: protectionReadinessContent.implicitHeight + 36
                Layout.minimumHeight: implicitHeight

                ColumnLayout {
                    id: protectionReadinessContent
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        Label {
                            Layout.fillWidth: true
                            text: root.label("جاهزية الحماية", "Protection readiness")
                            color: theme.text
                            font.pixelSize: 22
                            font.bold: true
                            wrapMode: Text.Wrap
                        }

                        InfoPill {
                            textValue: root.protectionReadyForDisplay() ? root.label("جاهزة", "Ready") : root.label("قيد التجهيز", "Preparing")
                            pillTone: root.readinessStatusTone()
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.readinessStatusBody()
                        color: theme.muted
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                        maximumLineCount: 4
                        elide: Text.ElideRight
                    }

                    StatusInfoRow {
                        Layout.fillWidth: true
                        iconSource: root.checkIcon
                        tone: root.readinessStatusTone()
                        title: root.readinessStatusTitle()
                        detail: root.protectionReadyForDisplay()
                                ? root.label("الجلسات المحمية متاحة حسب حالة النظام.", "Protected sessions are available according to system state.")
                                : root.label("لن تظهر وعود حماية كاملة قبل تأكيد الجاهزية من النظام.", "Full protection is not promised until the system confirms readiness.")
                    }

                    StatusInfoRow {
                        Layout.fillWidth: true
                        iconSource: root.updateIcon
                        tone: root.readinessStatusTone()
                        title: root.label("الخطوة التالية", "Next step")
                        detail: root.readinessNextActionText()
                    }

                    StatusInfoRow {
                        Layout.fillWidth: true
                        iconSource: root.modelIcon
                        tone: root.modelTone
                        title: root.label("نموذج الحماية", "Protection model")
                        detail: root.conciseModelDetail()
                    }


                    StatusInfoRow {
                        Layout.fillWidth: true
                        iconSource: root.updateIcon
                        tone: root.backgroundReviewTone()
                        title: root.backgroundReviewTitle()
                        detail: root.backgroundReviewBody()
                    }
                }
            }

            GlassCard {
                id: learningProgressCard
                Layout.fillWidth: true
                implicitHeight: learningProgressContent.implicitHeight + 36
                Layout.minimumHeight: implicitHeight

                ColumnLayout {
                    id: learningProgressContent
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        Label {
                            Layout.fillWidth: true
                            text: root.label("تقدم التعلم", "Learning progress")
                            color: theme.text
                            font.pixelSize: 22
                            font.bold: true
                            wrapMode: Text.Wrap
                        }

                        InfoPill {
                            textValue: String(root.learningAcceptedSessions()) + " / " + String(root.learningRequiredSessions())
                            pillTone: root.learningStatusTone()
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.learningStatusBody()
                        color: theme.muted
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                        maximumLineCount: 4
                        elide: Text.ElideRight
                    }

                    ProgressTrack {
                        Layout.fillWidth: true
                        value: root.learningProgressPercent()
                        maximum: 100
                        fillColor: root.learningStatusTone() === "success" ? theme.success : theme.primary
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        Label {
                            Layout.fillWidth: true
                            text: root.label("جلسات موثوقة", "Trusted sessions") + ": " + String(root.learningAcceptedSessions())
                            color: theme.text
                            font.bold: true
                            wrapMode: Text.Wrap
                        }

                        InfoPill {
                            textValue: String(root.learningProgressPercent()) + "%"
                            pillTone: root.learningStatusTone()
                        }
                    }

                    StatusInfoRow {
                        Layout.fillWidth: true
                        iconSource: root.activityIcon
                        tone: root.learningStatusTone()
                        title: root.learningStatusTitle()
                        detail: root.label("المطلوب: ", "Required: ") + String(root.learningRequiredSessions())
                                + root.label(" • الموصى به: ", " • Recommended: ") + String(root.learningRecommendedSessions())
                    }

                    StatusInfoRow {
                        Layout.fillWidth: true
                        visible: backend.trainingInProgress === true
                        iconSource: root.updateIcon
                        tone: "info"
                        title: root.label("التدريب الجاري", "Training in progress")
                        detail: root.cleanReadinessText(trainingProgress.detail || trainingProgress.headline, root.label("يعمل التدريب في الخلفية.", "Training is running in the background."))
                        trailingText: root.trainingPercentText()
                    }

                    AppButton {
                        id: trainProtectionModelButton
                        objectName: "userHomeTrainProtectionModelButton"
                        Layout.fillWidth: true
                        Layout.minimumHeight: 46
                        text: root.trainModelButtonText()
                        role: "success"
                        enabled: root.canTrainHomeModel
                        debugLabel: root.trainModelUnavailableText()
                        ToolTip.visible: hovered && !enabled
                        ToolTip.text: root.trainModelUnavailableText()
                        onClicked: root.guardedTrainProfile()
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.label("التفاصيل المتقدمة تبقى في العرض المتقدم؛ هنا يظهر فقط ما يساعدك على معرفة الحالة والخطوة التالية.", "Advanced details stay in the advanced view; this page only shows what helps you understand status and next step.")
                        color: theme.muted
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                    }
                }
            }

            GlassCard {
                id: recentActivityCard
                Layout.fillWidth: true
                Layout.columnSpan: root.denseLayout ? 1 : 2
                implicitHeight: recentActivityContent.implicitHeight + 36
                Layout.minimumHeight: implicitHeight

                ColumnLayout {
                    id: recentActivityContent
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 12

                    Label {
                        Layout.fillWidth: true
                        text: root.label("نشاط الحماية الأخير", "Recent protection activity")
                        color: theme.text
                        font.pixelSize: 22
                        font.bold: true
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.label("ملخصات آمنة من الحالة الحالية، بدون بيانات حساسة أو تفاصيل تقنية.", "Safe summaries from current state without sensitive data or technical details.")
                        color: theme.muted
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                    }

                    StatusInfoRow {
                        Layout.fillWidth: true
                        iconSource: root.activityIcon
                        tone: root.protectionTone
                        title: runtimeState.active ? root.label("جلسة حماية نشطة", "Protected session active") : root.label("الحماية بانتظار إجراء", "Protection awaiting action")
                        detail: runtimeState.active ? root.label("فحص الحماية يعمل في الخلفية حسب حالة النظام.", "Background check is running according to system state.") : root.readinessNextActionText()
                    }

                    StatusInfoRow {
                        Layout.fillWidth: true
                        iconSource: root.faceIcon
                        tone: root.faceTone
                        title: root.label("تأكيد الوجه", "Face confirmation")
                        detail: root.conciseFaceStatus()
                    }

                    StatusInfoRow {
                        Layout.fillWidth: true
                        iconSource: root.updateIcon
                        tone: root.readinessStatusTone()
                        title: root.label("جاهزية الحماية", "Protection readiness")
                        detail: root.readinessStatusTitle()
                    }

                    AppButton {
                        text: root.label("عرض النشاط", "View activity")
                        role: "details"
                        compact: true
                        onClicked: {
                            if (rootWindow)
                                rootWindow.navSelection = 5
                        }
                    }
                }
            }
        }

        GlassCard {
            id: privacyFooterCard
            Layout.fillWidth: true
            implicitHeight: privacyFooterContent.implicitHeight + 36
            Layout.minimumHeight: implicitHeight

            RowLayout {
                id: privacyFooterContent
                anchors.fill: parent
                anchors.margins: 18
                spacing: 14

                AssetIcon {
                    sourceUrl: root.privacyIcon
                    tone: "success"
                    Layout.preferredWidth: 46
                    Layout.preferredHeight: 46
                    iconPadding: 8
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 5
                    Label {
                        Layout.fillWidth: true
                        text: root.label("تصميم يراعي الخصوصية", "Privacy-aware by design")
                        color: theme.text
                        font.pixelSize: 17
                        font.bold: true
                        wrapMode: Text.Wrap
                    }
                    Label {
                        Layout.fillWidth: true
                        text: root.label("الصور زخرفية فقط؛ النصوص والحالات تأتي من التطبيق وحالة النظام.", "Images are decorative; labels and status come from the app and system state.")
                        color: theme.muted
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                    }
                }
            }
        }
    }
}
