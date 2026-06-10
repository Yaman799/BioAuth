import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"
import "../../theme/Ui.js" as Ui

ScrollView {
    id: root
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property bool sessionActionInFlight: false
    readonly property bool canStartProtectedSession: backend.canStartProtected === true && !sessionActionInFlight
    readonly property bool backendReportsAnySessionCanStop: backend.canStop === true
    readonly property bool canStopProtectedSession: backend.canStopProductionMonitor === true && !sessionActionInFlight
    readonly property bool denseLayout: width < 980
    readonly property bool narrowActions: width < 720
    readonly property var runtimeState: backend.runtimeState || ({})
    readonly property var productionApproval: backend.productionApprovalState || ({})
    readonly property var modelState: backend.modelReadinessState || ({})
    readonly property string runtimeTone: runtimeState.active ? (runtimeState.statusTone || "success") : (backend.statusTone || "info")
    readonly property url heroImage: Qt.resolvedUrl("../../assets/bioauth/01_hero_integrated/03_live_protection_pulse_integrated.png")
    readonly property url sessionIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/10_session_monitor.png")
    readonly property url pulseIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/24_pulse.png")
    readonly property url checkIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/18_check_success.png")
    readonly property url warningIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/19_warning.png")
    readonly property url realtimeIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/37_live_realtime.png")
    readonly property url privacyIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/06_privacy_lock.png")
    readonly property url updateIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/04_updates_refresh.png")

    clip: true
    contentWidth: availableWidth

    Timer {
        id: sessionActionGuardTimer
        interval: 1200
        repeat: false
        onTriggered: root.sessionActionInFlight = false
    }

    Connections {
        target: backend
        function onControlsChanged() { root.sessionActionInFlight = false }
        function onRuntimeStateChanged() { root.sessionActionInFlight = false }
        function onStatusChanged() { root.sessionActionInFlight = false }
    }

    function label(arText, enText) {
        return Ui.trx(backend.language === "ar", arText, enText)
    }

    function tourTarget(name) {
        if (name === "protectionHero") return protectionHeroCard
        if (name === "protectionFlow") return protectionFlowCard
        if (name === "protectionControl") return protectionControlCard
        return null
    }

    function isAttentionTone(tone) {
        var t = String(tone || "").toLowerCase()
        return t === "warn" || t === "warning" || t === "danger" || t === "error"
    }

    function userSafeText(value, fallbackText) {
        // For protection-page runtime text, use backend.safeProtectionText when
        // the value matches the current status message.  Otherwise apply the
        // defence-in-depth keyword guard.
        var text = String(value || "")
        if (text.length === 0)
            return fallbackText || ""
        if (backend.userSafeProtectionText !== undefined)
            return backend.userSafeProtectionText(text, fallbackText || "")
        if (text === backend.statusMessage && backend.safeProtectionText !== undefined)
            return backend.safeProtectionText || fallbackText || ""
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
            if (lower.indexOf("suspicious") >= 0 || lower.indexOf("attention") >= 0 || lower.indexOf("fail") >= 0 || lower.indexOf("mismatch") >= 0)
                return root.label("مراجعة تحديث الحماية تحتاج انتباهًا", "Protection update review needs attention")
            if (lower.indexOf("pending") >= 0 || lower.indexOf("waiting") >= 0 || lower.indexOf("partial") >= 0 || lower.indexOf("collecting") >= 0)
                return root.label("يتم جمع أدلة آمنة قبل إتاحة التحديث.", "Safe evidence is being collected before the update becomes available.")
            return root.label("تحديث الحماية قيد المراجعة في الخلفية.", "A protection update is being reviewed in the background.")
        }
        if (lower.indexOf("face") >= 0 && lower.indexOf("model") >= 0 && (lower.indexOf("missing") >= 0 || lower.indexOf("not found") >= 0))
            return root.label("إعداد تأكيد الوجه مطلوب", "Face confirmation needs setup")
        if (false)
            return root.label("فحص نموذج الحماية", "Protection model check")
        if (false)
            return root.label("تتم مراجعة تفاصيل الحماية.", "Protection details are being reviewed.")
        if (false)
            return root.label("تتم مراجعة جاهزية الحماية قبل إتاحة الإجراء.", "Protection readiness is being reviewed before the action becomes available.")
        return text
    }

    function guardedStartProtected() {
        if (!root.canStartProtectedSession)
            return
        root.sessionActionInFlight = true
        sessionActionGuardTimer.restart()
        backend.requestUserStartProtection()
    }

    function guardedStopProtected() {
        if (!root.canStopProtectedSession)
            return
        root.sessionActionInFlight = true
        sessionActionGuardTimer.restart()
        backend.requestUserStopProtection()
    }

    function heroSummaryText() {
        if (runtimeState.active)
            return root.label("تعمل الحماية الآن وتعرض الصفحة الحالة التي يؤكدها النظام فقط.", "Protection is running now; this page shows only system-confirmed state.")
        if (backend.canStartProtected === true)
            return root.label("يمكنك بدء جلسة محمية. ستظهر المؤشرات بعد توفر دليل كافٍ.", "You can start a protected session. Signals appear after enough evidence is available.")
        return root.userSafeText(runtimeState.runtimeDisplayText || backend.statusMessage, backend.tr("user_protection_status_body"))
    }

    function statusMetricValue() {
        if (runtimeState.active)
            return root.label("فحص حماية قيد التقدم", "Background check in progress")
        if (backend.canStartProtected === true)
            return root.label("جاهز للبدء", "Ready to start")
        if (root.isAttentionTone(root.runtimeTone))
            return root.label("يحتاج انتباهًا", "Needs attention")
        return root.label("بانتظار", "Waiting")
    }

    function decisionMetricValue() {
        var decision = root.userSafeText(runtimeState.decisionText, "")
        if (decision.length > 0)
            return decision
        if (root.isAttentionTone(root.runtimeTone))
            return root.label("يحتاج انتباهًا", "Needs attention")
        if (runtimeState.active && String(root.runtimeTone).toLowerCase() === "success")
            return root.label("طبيعي", "Normal")
        if (runtimeState.active)
            return root.label("قيد المراجعة", "Pending")
        return root.label("بانتظار", "Waiting")
    }

    function riskMetricValue() {
        var risk = root.userSafeText(runtimeState.riskText, "")
        if (risk.length > 0)
            return risk
        if (root.isAttentionTone(root.runtimeTone))
            return root.label("يحتاج انتباهًا", "Needs attention")
        if (runtimeState.active && String(root.runtimeTone).toLowerCase() === "success")
            return root.label("هادئ", "Calm")
        return root.label("بانتظار", "Waiting")
    }

    function freshnessMetricValue() {
        if (runtimeState.elapsed)
            return root.label("محدّث مؤخراً", "Updated recently")
        return root.label("بانتظار", "Waiting")
    }

    function freshnessDetail() {
        if (runtimeState.elapsed)
            return runtimeState.elapsed
        return root.label("تظهر الحداثة بعد وصول تحديثات الجلسة.", "Freshness appears after session updates arrive.")
    }

    function backgroundReviewActive() {
        var status = String(productionApproval.modelStatus || productionApproval.model_status || modelState.modelStatus || modelState.status || "").toLowerCase()
        var action = String(modelState.backgroundAction || modelState.background_action || "").toLowerCase()
        return status.indexOf("sha" + "dow") >= 0 || status.indexOf("pending") >= 0 || status.indexOf("review") >= 0 || action.indexOf("validation") >= 0 || action.indexOf("review") >= 0
    }

    function backgroundReviewStatusText() {
        if (root.backgroundReviewActive())
            return root.label("تحديث الحماية قيد المراجعة في الخلفية. لا يؤثر على الجلسة الحالية ولا يملك قرار القفل.", "A protection update is being reviewed in the background. It does not affect the current session and cannot make lock decisions.")
        return root.label("لا يوجد تحديث حماية يحتاج إجراءً الآن.", "No protection update needs action right now.")
    }

    ColumnLayout {
        width: root.availableWidth
        spacing: 18

        GlassCard {
            id: protectionHeroCard
            Layout.fillWidth: true
            implicitHeight: Math.max(root.denseLayout ? 760 : 470, protectionHeroContent.implicitHeight + (root.denseLayout ? 32 : 44))
            Layout.minimumHeight: implicitHeight

            RowLayout {
                id: protectionHeroContent
                anchors.fill: parent
                anchors.margins: root.denseLayout ? 16 : 22
                spacing: root.denseLayout ? 14 : 22

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: root.denseLayout ? protectionHeroCard.width : protectionHeroCard.width * 0.60
                    Layout.maximumWidth: root.denseLayout ? protectionHeroCard.width : protectionHeroCard.width * 0.62
                    spacing: 14

                    InfoPill {
                        textValue: root.statusMetricValue()
                        pillTone: root.runtimeTone
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.label("مركز الحماية المباشر", "Live Protection Center")
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
                            Layout.minimumHeight: 122
                            compact: true
                            iconSource: root.sessionIcon
                            tone: root.runtimeTone
                            title: root.label("الحالة", "Status")
                            value: root.statusMetricValue()
                            detail: root.label("تعتمد على حالة الجلسة الحالية.", "Based on current session state.")
                        }

                        PremiumMetricCard {
                            Layout.fillWidth: true
                            Layout.minimumHeight: 122
                            compact: true
                            iconSource: root.checkIcon
                            tone: root.runtimeTone
                            title: root.label("القرار", "Decision")
                            value: root.decisionMetricValue()
                            detail: root.label("لا يظهر قرار إلا عند توفره.", "A decision appears only when available.")
                        }

                        PremiumMetricCard {
                            Layout.fillWidth: true
                            Layout.minimumHeight: 122
                            compact: true
                            iconSource: root.pulseIcon
                            tone: root.runtimeTone
                            title: root.label("إشارة الخطر", "Risk signal")
                            value: root.riskMetricValue()
                            detail: root.label("ملخص مبسّط من حالة الحماية.", "A simplified protection-state summary.")
                        }

                        PremiumMetricCard {
                            Layout.fillWidth: true
                            Layout.minimumHeight: 122
                            compact: true
                            iconSource: root.realtimeIcon
                            tone: runtimeState.elapsed ? "success" : "info"
                            title: root.label("الحداثة", "Freshness")
                            value: root.freshnessMetricValue()
                            detail: root.freshnessDetail()
                        }
                    }
                }

                Item {
                    visible: !root.denseLayout
                    Layout.preferredWidth: protectionHeroCard.width * 0.38
                    Layout.fillHeight: true

                    HeroAssetFrame {
                        anchors.fill: parent
                        anchors.leftMargin: 4
                        sourceUrl: root.heroImage
                        tone: root.runtimeTone
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

        GridLayout {
            Layout.fillWidth: true
            columns: root.denseLayout ? 1 : 2
            columnSpacing: 18
            rowSpacing: 18

            GlassCard {
                id: protectionFlowCard
                Layout.fillWidth: true
                implicitHeight: protectionFlowContent.implicitHeight + 36
                Layout.minimumHeight: implicitHeight

                ColumnLayout {
                    id: protectionFlowContent
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 12

                    Label {
                        Layout.fillWidth: true
                        text: root.label("ماذا يفعل BioAuth الآن", "What BioAuth is doing now")
                        color: theme.text
                        font.pixelSize: 22
                        font.bold: true
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.label("نظرة مبسطة على خطوات الحماية الحالية بلغة واضحة.", "A simple view of the current protection steps in plain language.")
                        color: theme.muted
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                    }

                    StoryboardStep {
                        Layout.fillWidth: true
                        stepNumber: 1
                        title: root.label("فحص إتاحة الجلسة", "Checking session availability")
                        detail: backend.canStartProtected || backend.canStop ? root.label("أزرار التحكم متاحة حسب حالة النظام.", "Session controls are available according to system state.") : root.label("ينتظر BioAuth إتاحة جلسة محمية.", "BioAuth is waiting for protected session availability.")
                        stateText: backend.canStartProtected || backend.canStop ? root.label("متاح", "Available") : root.label("بانتظار", "Waiting")
                        tone: backend.canStartProtected || backend.canStop ? "success" : "neutral"
                        active: !runtimeState.active
                    }

                    StoryboardStep {
                        Layout.fillWidth: true
                        stepNumber: 2
                        title: root.label("متابعة النشاط المحمي", "Watching protected activity")
                        detail: runtimeState.active ? root.label("الجلسة نشطة حسب حالة النظام الحالية.", "The session is active according to current system state.") : root.label("تبدأ المتابعة بعد بدء جلسة محمية.", "Watching starts after a protected session begins.")
                        stateText: runtimeState.active ? root.label("نشط", "Active") : root.label("غير نشط", "Idle")
                        tone: runtimeState.active ? "success" : "info"
                        active: runtimeState.active
                    }

                    StoryboardStep {
                        Layout.fillWidth: true
                        stepNumber: 3
                        title: root.label("مراجعة المؤشرات", "Reviewing signals")
                        detail: runtimeState.decisionText ? root.userSafeText(runtimeState.decisionText, "") : root.label("لا توجد نتيجة معروضة حتى يوفرها النظام.", "No outcome is shown until the system provides it.")
                        stateText: runtimeState.decisionText ? root.label("متاح", "Available") : root.label("بانتظار", "Waiting")
                        tone: runtimeState.decisionText ? root.runtimeTone : "neutral"
                        active: runtimeState.decisionText ? true : false
                    }

                    StoryboardStep {
                        Layout.fillWidth: true
                        stepNumber: 4
                        title: root.label("الاستجابة عند الحاجة", "Responding when needed")
                        detail: root.sessionActionInFlight ? backend.tr("user_action_in_progress") : root.userSafeText(backend.statusMessage, backend.tr("user_protection_ready_hint"))
                        stateText: root.sessionActionInFlight ? backend.tr("user_action_working") : root.label("حسب الحالة", "Status-based")
                        tone: root.sessionActionInFlight ? "info" : root.runtimeTone
                        active: root.sessionActionInFlight
                    }


                    StoryboardStep {
                        Layout.fillWidth: true
                        stepNumber: 5
                        title: root.label("مراجعة التحديثات بأمان", "Safe update review")
                        detail: root.backgroundReviewStatusText()
                        stateText: root.backgroundReviewActive() ? root.label("قيد المراجعة", "Reviewing") : root.label("هادئ", "Quiet")
                        tone: root.backgroundReviewActive() ? "info" : "neutral"
                        active: root.backgroundReviewActive()
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 18

                GlassCard {
                    id: protectionControlCard
                    Layout.fillWidth: true
                    implicitHeight: protectionControlContent.implicitHeight + 36
                    Layout.minimumHeight: implicitHeight

                    ColumnLayout {
                        id: protectionControlContent
                        anchors.fill: parent
                        anchors.margins: 18
                        spacing: 12

                        Label {
                            Layout.fillWidth: true
                            text: root.label("تحكم بالحماية", "Control your protection")
                            color: theme.text
                            font.pixelSize: 22
                            font.bold: true
                            wrapMode: Text.Wrap
                        }

                        Label {
                            Layout.fillWidth: true
                            text: root.sessionActionInFlight ? backend.tr("user_action_in_progress") : root.userSafeText(backend.statusMessage, backend.tr("user_protection_ready_hint"))
                            color: root.sessionActionInFlight ? theme.accent : theme.muted
                            font.pixelSize: 13
                            wrapMode: Text.Wrap
                            maximumLineCount: 3
                            elide: Text.ElideRight
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: root.narrowActions ? 1 : 2
                            columnSpacing: 12
                            rowSpacing: 10

                            AppButton {
                                Layout.fillWidth: true
                                Layout.minimumHeight: 44
                                text: root.sessionActionInFlight ? backend.tr("user_action_working") : backend.tr("start_protected")
                                role: "primary"
                                enabled: root.canStartProtectedSession
                                ToolTip.visible: hovered && !enabled
                                ToolTip.text: root.sessionActionInFlight ? backend.tr("user_action_in_progress") : backend.tr("user_protection_start_unavailable_tooltip")
                                onClicked: root.guardedStartProtected()
                            }

                            AppButton {
                                Layout.fillWidth: true
                                Layout.minimumHeight: 44
                                text: root.sessionActionInFlight ? backend.tr("user_action_working") : backend.tr("stop_session")
                                role: "neutral"
                                enabled: root.canStopProtectedSession
                                ToolTip.visible: hovered && !enabled
                                ToolTip.text: root.sessionActionInFlight ? backend.tr("user_action_in_progress") : backend.tr("user_protection_stop_unavailable_tooltip")
                                onClicked: root.guardedStopProtected()
                            }
                        }

                        StatusInfoRow {
                            Layout.fillWidth: true
                            iconSource: root.privacyIcon
                            tone: "success"
                            title: backend.tr("user_protection_privacy_title")
                            detail: backend.tr("user_protection_privacy_body")
                        }
                    }
                }

                GlassCard {
                    id: protectionSessionNoteCard
                    Layout.fillWidth: true
                    implicitHeight: protectionSessionNoteContent.implicitHeight + 36
                    Layout.minimumHeight: implicitHeight

                    ColumnLayout {
                        id: protectionSessionNoteContent
                        anchors.fill: parent
                        anchors.margins: 18
                        spacing: 8

                        Label {
                            Layout.fillWidth: true
                            text: runtimeState.active ? root.label("جلسة حماية نشطة", "Protected session active") : root.label("لا توجد جلسة نشطة حالياً", "No active protected session right now")
                            color: theme.text
                            font.pixelSize: 19
                            font.bold: true
                            wrapMode: Text.Wrap
                        }

                        Label {
                            Layout.fillWidth: true
                            text: runtimeState.active ? root.label("يستمر فحص الحماية في الخلفية حتى تتغير حالة النظام.", "The background check continues until system state changes.") : root.label("ابدأ جلسة محمية عندما يعلن النظام أنها متاحة.", "Start a protected session when the system reports it is available.")
                            color: theme.muted
                            font.pixelSize: 13
                            wrapMode: Text.Wrap
                            maximumLineCount: 4
                            elide: Text.ElideRight
                        }


                        StatusInfoRow {
                            Layout.fillWidth: true
                            iconSource: root.updateIcon
                            tone: root.backgroundReviewActive() ? "info" : "neutral"
                            title: root.label("تحديثات الحماية", "Protection updates")
                            detail: root.backgroundReviewStatusText()
                        }
                    }
                }
            }
        }
    }
}
