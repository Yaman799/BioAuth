import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

GlassCard {
    id: panel
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property bool compact: width < 920
    property bool dense: width < 720
    property var runtime: backend.runtimeState || ({})
    property var productionApproval: backend.productionApprovalState || ({})
    property var modelReadiness: backend.modelReadinessState || ({})
    readonly property var shadowLoop: modelReadiness.shadowLoopState || ({})
    readonly property var autoPromotion: productionApproval.autoPromotionState || ({})
    readonly property var evidenceGate: productionApproval.productionEvidenceSummary || productionApproval.production_evidence_summary || modelReadiness.evidenceGateState || ({})
    readonly property var remediation: productionApproval.remediationState || productionApproval.remediation_state || modelReadiness.remediationState || ({})
    property real displayRiskAnimated: 0
    property bool displayRiskAnimationReady: false
    readonly property real displayRiskTargetValue: computeDisplayRiskTarget()

    function trx(arText, enText) { return rootWindow ? rootWindow.trx(arText, enText) : enText }
    function safeText(value, fallback) {
        if (value === undefined || value === null || String(value).length === 0)
            return fallback
        return String(value)
    }
    function computeDisplayRiskTarget() {
        var riskText = runtime.displayRiskAvailable === true ? runtime.displayRiskText : runtime.riskText
        var value = Number(riskText)
        if (isNaN(value))
            return displayRiskAnimated || 0
        return Math.max(0, Math.min(100, value))
    }
    function formatRiskNumber(value) {
        if (Math.abs(value - Math.round(value)) < 0.05)
            return String(Math.round(value))
        return Number(value).toFixed(1)
    }
    function listText(value, fallback) {
        if (value === undefined || value === null)
            return fallback
        if (value.length !== undefined && value.join !== undefined && value.length > 0)
            return value.join(", ")
        var text = String(value)
        return text.length > 0 ? text : fallback
    }
    function countsText(required, current) {
        var parts = []
        if (required === undefined || required === null)
            return trx("لا توجد متطلبات أدلة جديدة", "No new evidence requirements")
        for (var key in required) {
            var need = Number(required[key] || 0)
            if (need <= 0)
                continue
            var have = current && current[key] !== undefined ? Number(current[key] || 0) : 0
            parts.push(key + ": " + have + "/" + need)
        }
        return parts.length > 0 ? parts.join(", ") : trx("لا توجد متطلبات أدلة جديدة", "No new evidence requirements")
    }
    function toneColor(tone) { return rootWindow ? rootWindow.toneColor(tone) : theme.info }
    function liveTone() {
        var displayTone = safeText(runtime.runtimeDisplayTone, "")
        if (displayTone.length > 0)
            return displayTone
        if (runtime.technicalFailure || runtime.protectedStartupPhase === "logger_failed" || runtime.protectedStartupPhase === "monitor_failed")
            return "danger"
        if (runtime.historyFinalizing === true)
            return "warn"
        if (runtime.awaitingEvidence || runtime.protectedStartupPhase === "starting_logger" || runtime.protectedStartupPhase === "starting_monitor" || runtime.protectedStartupPhase === "collecting_evidence" || runtime.protectedStartupPhase === "telemetry_unavailable")
            return "warn"
        if (runtime.active)
            return "success"
        return "neutral"
    }
    function liveLabel() {
        var displayPhase = safeText(runtime.runtimeDisplayPhase, "")
        if (displayPhase === "suspicious_lock_delayed")
            return trx("قفل مؤجل", "LOCK DELAYED")
        if (displayPhase === "suspicious_warning")
            return trx("تحذير", "WARNING")
        if (displayPhase === "waiting_for_settled_evidence")
            return trx("انتظار استقرار", "SETTLING")
        if (displayPhase === "post_resume_verification")
            return trx("تحقق العودة", "VERIFYING")
        if (displayPhase === "enrollment_capture")
            return trx("التسجيل", "ENROLLMENT")
        if (displayPhase === "lock_confirmed")
            return trx("قفل مؤكد", "LOCK CONFIRMED")
        var phase = safeText(runtime.protectedStartupPhase, "")
        if (phase === "logger_failed")
            return trx("فشل المسجل", "LOGGER FAILED")
        if (phase === "monitor_failed")
            return trx("فشل المراقبة", "MONITOR FAILED")
        if (phase === "starting_logger")
            return trx("بدء المسجل", "LOGGER STARTING")
        if (phase === "starting_monitor")
            return trx("بدء المراقبة", "MONITOR STARTING")
        if (phase === "collecting_evidence")
            return trx("يجمع أدلة", "COLLECTING")
        if (phase === "telemetry_unavailable")
            return trx("التليمترية غير متاحة", "TELEMETRY UNAVAILABLE")
        if (runtime.historyFinalizing === true)
            return trx("إنهاء الأرشيف", "FINALIZING")
        if (runtime.technicalFailure)
            return trx("خلل تقني", "Technical issue")
        if (runtime.awaitingEvidence)
            return trx("يجمع أدلة", "Collecting evidence")
        if (runtime.active)
            return trx("LIVE", "LIVE")
        return trx("STANDBY", "STANDBY")
    }
    function decisionValue() {
        return safeText(runtime.trustLabel, safeText(runtime.decisionLabel, safeText(runtime.decisionText, "—")))
    }
    function riskValue() {
        if (runtime.displayRiskAvailable === true || runtime.riskAvailable === true)
            return formatRiskNumber(displayRiskAnimated)
        return safeText(runtime.riskUnavailableText, safeText(runtime.runtimeStatusText, "--"))
    }

    Component.onCompleted: {
        displayRiskAnimated = displayRiskTargetValue
        displayRiskAnimationReady = true
    }

    onDisplayRiskTargetValueChanged: {
        if (!displayRiskAnimationReady) {
            displayRiskAnimated = displayRiskTargetValue
            displayRiskAnimationReady = true
        } else {
            displayRiskAnimated = displayRiskTargetValue
        }
    }

    Behavior on displayRiskAnimated {
        NumberAnimation { duration: 620; easing.type: Easing.OutCubic }
    }
    function evidenceValue() {
        return safeText(runtime.inputPipelineStatus, safeText(runtime.protectedStartupPhase, safeText(runtime.runtimeDisplayPhase, "--")))
    }
    function runtimeIsShadowEvidenceMode() {
        var values = [runtime.runtimeStatus, runtime.status, runtime.statusCode, runtime.mode, runtime.runtimeMode, runtime.sessionKind, runtime.session_kind, runtime.evidenceSource, runtime.evidence_source, runtime.runtimeTelemetrySource, runtime.telemetrySource, runtime.flow]
        for (var i = 0; i < values.length; i++) {
            var value = String(values[i] || "").toLowerCase()
            if (value.indexOf("shadow_evidence") >= 0)
                return true
        }
        return false
    }
    function runtimeExplanation() {
        var shadowFallback = trx("التحقق الخلفي يسجل أدلة فقط؛ إنفاذ القفل معطل في هذا الوضع.", "Background validation records evidence only; lock enforcement is disabled in this mode.")
        if (runtimeIsShadowEvidenceMode()) {
            var shadowContext = safeText(runtime.escalationPolicyText, "")
            if (shadowContext.length <= 0 && runtime.lockSuppressionActive === true)
                shadowContext = safeText(runtime.lockSuppressionReasonText, "")
            if (shadowContext.length <= 0 && runtime.evidenceStallActive === true)
                shadowContext = safeText(runtime.evidenceStallReasonText, safeText(runtime.expectedNextWindowHint, ""))
            if (shadowContext.length <= 0)
                shadowContext = safeText(runtime.evidenceWaitingReasonText, safeText(runtime.diagnosticText, safeText(runtime.statusDetail, safeText(runtime.protectedFailureReason, ""))))
            if (shadowContext.length > 0) {
                var lowerShadowContext = shadowContext.toLowerCase()
                if (lowerShadowContext.indexOf("simulated only") >= 0 && (lowerShadowContext.indexOf("lock enforcement") >= 0 || lowerShadowContext.indexOf("protected sessions") >= 0))
                    return shadowFallback
                return productSafeStatusText(shadowContext) + " " + shadowFallback
            }
            return shadowFallback
        }
        if (runtime.lockSuppressionActive === true)
            return safeText(runtime.lockSuppressionReasonText, safeText(runtime.escalationPolicyText, "--"))
        if (runtime.evidenceStallActive === true)
            return safeText(runtime.evidenceStallReasonText, safeText(runtime.expectedNextWindowHint, "--"))
        return safeText(runtime.evidenceWaitingReasonText, safeText(runtime.escalationPolicyText, safeText(runtime.diagnosticText, safeText(runtime.statusDetail, safeText(runtime.protectedFailureReason, "--")))))
    }
    function sourceText() {
        var source = safeText(runtime.runtimeTelemetrySource, safeText(runtime.telemetrySource, ""))
        if (source.length > 0)
            return source
        if (runtime.active)
            return trx("live session logs", "live session logs")
        return trx("waiting for protected session", "waiting for protected session")
    }
    function freshnessText() {
        var age = safeText(runtime.telemetryAgeText, "")
        if (age.length > 0)
            return age
        if (runtime.historyFinalizing === true)
            return safeText(runtime.historySyncStatusText, trx("finalizing session archive", "finalizing session archive"))
        return runtime.active ? trx("updates with runtime refresh", "updates with runtime refresh") : trx("not active", "not active")
    }

    function modeTitle(mode) {
        if (mode === "hybrid")
            return trx("حماية محسّنة", "Enhanced protection")
        if (mode === "hybrid_accelerated")
            return trx("حماية محسّنة أسرع", "Faster enhanced protection")
        return trx("المحرك الأساسي", "Core engine")
    }
    function activeProtectionModeText() {
        return modeTitle(safeText(backend.deepRuntimeEffectiveMode, "classic"))
    }
    function fallbackReasonText() {
        return safeText(backend.deepRuntimeFallbackReasonText, "")
    }
    function setupStatusText() {
        if (productionApproval.protectedSessionsAvailable === true)
            return trx("Protected Sessions are ready.", "Protected Sessions are ready.")
        if (shadowLoop.active === true || productionApproval.modelStatus === "approved_for_shadow")
            return trx("BioAuth is validating your protection model safely in the background.", "BioAuth is validating your protection model safely in the background.")
        if (modelReadiness.backgroundAction === "training_in_background")
            return trx("Training your protection model in the background.", "Training your protection model in the background.")
        return safeText(modelReadiness.safeUserMessage, safeText(productionApproval.safeRecommendationText, trx("BioAuth is improving your protection model in the background.", "BioAuth is improving your protection model in the background.")))
    }
    function setupStatusTone() {
        if (productionApproval.protectedSessionsAvailable === true)
            return "success"
        if (shadowLoop.active === true || productionApproval.modelStatus === "approved_for_shadow")
            return "warn"
        if (modelReadiness.backgroundAction === "training_in_background")
            return "info"
        return "details"
    }
    function productSafeStatusText(value) {
        var text = safeText(value, "--")
        if (text === "approved_for_shadow")
            return trx("قيد التحقق", "validation pending")
        if (text === "shadow_only")
            return trx("أدلة فقط", "evidence only")
        if (text === "collecting_targeted_sessions")
            return trx("جاري جمع جلسات تحقق", "collecting validation sessions")
        if (text.indexOf("shadow") >= 0 || text.indexOf("Shadow") >= 0)
            return text.replace(/shadow/gi, "background validation").replace(/_/g, " ")
        return text
    }

    implicitHeight: contentColumn.implicitHeight + 40

    ColumnLayout {
        id: contentColumn
        anchors.fill: parent
        anchors.margins: panel.dense ? 16 : 22
        spacing: 14

        RowLayout {
            Layout.fillWidth: true
            spacing: 12

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 5
                Label {
                    text: trx("Live Telemetry Pulse", "Live Telemetry Pulse")
                    color: theme.text
                    font.pixelSize: panel.dense ? 20 : 25
                    font.bold: true
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
                Label {
                    text: trx("قراءة مباشرة من حالة الجلسة الحية، تظهر القرار والمخاطر ومصدر الإشارة بدون بيانات وهمية.", "A direct read from the live-session state, showing decision, risk, and signal source without fake data.")
                    color: theme.muted
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
            }

            Rectangle {
                radius: 999
                color: toneColor(panel.liveTone())
                implicitWidth: liveBadgeText.implicitWidth + 24
                implicitHeight: 34
                Label {
                    id: liveBadgeText
                    anchors.centerIn: parent
                    text: panel.liveLabel()
                    color: theme.chipText || "white"
                    font.bold: true
                    font.pixelSize: 12
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: panel.compact ? 2 : 4
            columnSpacing: 10
            rowSpacing: 10

            Repeater {
                model: [
                    { title: trx("Status", "Status"), value: safeText(runtime.runtimeDisplayText, safeText(runtime.runtimeStatusText, safeText(runtime.statusLabel, safeText(runtime.activeText, backend.tr("status_idle"))))), tone: liveTone() },
                    { title: trx("Decision", "Decision"), value: decisionValue(), tone: runtime.trustTone || (rootWindow ? rootWindow.decisionTone(runtime.decisionText) : "info") },
                    { title: trx("Risk", "Risk"), value: riskValue(), tone: runtime.riskAvailable === true ? "warn" : liveTone() },
                    { title: trx("Evidence", "Evidence"), value: evidenceValue(), tone: liveTone() }
                ]
                delegate: Rectangle {
                    Layout.fillWidth: true
                    radius: 16
                    color: theme.surface4
                    border.color: toneColor(modelData.tone)
                    border.width: 1
                    implicitHeight: 88

                    Behavior on color { ColorAnimation { duration: 260; easing.type: Easing.OutCubic } }
                    Behavior on border.color { ColorAnimation { duration: 420; easing.type: Easing.OutCubic } }
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 4
                        Label { text: modelData.title; color: theme.muted; font.pixelSize: 12; elide: Text.ElideRight; Layout.fillWidth: true }
                        Label { text: modelData.value; color: theme.text; font.pixelSize: panel.dense ? 17 : 20; font.bold: true; elide: Text.ElideRight; Layout.fillWidth: true }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            radius: 18
            color: theme.surface1
            border.color: toneColor(setupStatusTone())
            border.width: 1
            implicitHeight: setupStatusColumn.implicitHeight + 24

            Behavior on border.color { ColorAnimation { duration: 420; easing.type: Easing.OutCubic } }

            ColumnLayout {
                id: setupStatusColumn
                anchors.fill: parent
                anchors.margins: 12
                spacing: 7
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Label {
                        text: trx("Protection setup", "Protection setup")
                        color: theme.text
                        font.bold: true
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    InfoPill {
                        textValue: productionApproval.protectedSessionsAvailable === true ? trx("جاهزة", "Ready") : safeText(productionApproval.modelStatus, trx("قيد التحسين", "improving"))
                        pillTone: setupStatusTone()
                    }
                }
                Label {
                    text: setupStatusText()
                    color: theme.muted
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            radius: 18
            color: theme.surface1
            border.color: theme.border
            border.width: 1
            implicitHeight: feedColumn.implicitHeight + 24

            ColumnLayout {
                id: feedColumn
                anchors.fill: parent
                anchors.margins: 12
                spacing: 9

                Label {
                    text: trx("Live evidence feed", "Live evidence feed")
                    color: theme.text
                    font.bold: true
                    Layout.fillWidth: true
                }

                Repeater {
                    model: [
                        { label: trx("Flow", "Flow"), value: safeText(runtime.flow, "idle"), tone: "details" },
                        { label: trx("Elapsed", "Elapsed"), value: safeText(runtime.elapsed, "--"), tone: "details" },
                        { label: trx("Signal source", "Signal source"), value: sourceText(), tone: "info" },
                        { label: trx("Active protection", "Active protection"), value: activeProtectionModeText(), tone: backend.deepRuntimeIsFallback === true ? "warn" : "success" },
                        { label: trx("Fallback reason", "Fallback reason"), value: fallbackReasonText(), tone: "warn", visible: backend.deepRuntimeIsFallback === true },
                        { label: trx("Production approval", "Production approval"), value: productSafeStatusText(productionApproval.modelStatus), tone: productionApproval.protectedSessionsAvailable === true ? "success" : (productionApproval.modelStatus === "approved_for_shadow" ? "warn" : "details") },
                        { label: trx("Evidence gate", "Evidence gate"), value: productSafeStatusText(safeText(evidenceGate.status, safeText(modelReadiness.evidenceGateStatus, "partial"))) + " / " + productSafeStatusText(safeText(evidenceGate.promotion_effect, safeText(modelReadiness.evidencePromotionEffect, "shadow_only"))), tone: safeText(evidenceGate.status, safeText(modelReadiness.evidenceGateStatus, "partial")) === "pass" ? "success" : (safeText(evidenceGate.status, safeText(modelReadiness.evidenceGateStatus, "partial")) === "fail" ? "danger" : "warn") },
                        { label: trx("Evidence reasons", "Evidence reasons"), value: listText(evidenceGate.reason_codes || modelReadiness.evidenceReasonCodes, "production_evidence_partial"), tone: "details" },
                        { label: trx("Remediation", "Remediation"), value: safeText(remediation.status, safeText(modelReadiness.remediationStatus, "planned")) + " — " + safeText(remediation.next_action, safeText(modelReadiness.remediationNextAction, "wait_for_manual_review")), tone: remediation.retry_allowed === true || modelReadiness.retryAllowed === true ? "success" : "warn" },
                        { label: trx("Remediation progress", "Remediation progress"), value: countsText(remediation.required_counts || remediation.requiredCounts || remediation.required_new_evidence || remediation.requiredNewEvidence || modelReadiness.remediationRequiredCounts || modelReadiness.remediation_required_counts, remediation.current_counts || remediation.currentCounts || remediation.current_new_evidence || remediation.currentNewEvidence || modelReadiness.remediationCurrentCounts || modelReadiness.remediation_current_counts), tone: remediation.retry_allowed === true || remediation.retryAllowed === true || modelReadiness.retryAllowed === true ? "success" : "details" },
                        { label: trx("Retry eligibility", "Retry eligibility"), value: remediation.retry_allowed === true || remediation.retryAllowed === true || modelReadiness.retryAllowed === true ? trx("مسموح بعد أدلة جديدة", "allowed after new evidence") : trx("مقفلة حتى تكتمل الأدلة", "blocked until evidence is complete"), tone: remediation.retry_allowed === true || remediation.retryAllowed === true || modelReadiness.retryAllowed === true ? "success" : "warn" },
                        { label: trx("Auto promotion", "Auto promotion"), value: autoPromotion.enabled === true ? safeText(autoPromotion.lastReason, safeText(modelReadiness.backgroundAction, "enabled")) : "disabled", tone: autoPromotion.enabled === true ? "info" : "neutral" },
                        { label: trx("Background validation", "Background validation"), value: productSafeStatusText(shadowLoop.active === true ? safeText(shadowLoop.phase, "collecting_targeted_sessions") : safeText(modelReadiness.backgroundAction, "--")), tone: shadowLoop.active === true ? "info" : "details", visible: productionApproval.protectedSessionsAvailable !== true },
                        { label: trx("Protected lock reason", "Protected lock reason"), value: safeText(productionApproval.approvalReasonText, "--"), tone: "warn", visible: productionApproval.protectedSessionsAvailable !== true },
                        { label: trx("Freshness", "Freshness"), value: freshnessText(), tone: runtime.active ? "success" : "neutral" },
                        { label: trx("Why no lock?", "Why no lock?"), value: runtimeExplanation(), tone: runtime.lockSuppressionActive === true ? "warn" : (runtime.technicalFailure ? "danger" : "details") }
                    ]
                    delegate: RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        Rectangle {
                            width: 9
                            height: 9
                            radius: 9
                            color: toneColor(modelData.tone)
                        }
                        visible: modelData.visible !== false
                        Layout.preferredHeight: visible ? implicitHeight : 0
                        Label { text: modelData.label; color: theme.muted; font.pixelSize: 12; Layout.preferredWidth: panel.compact ? 92 : 130; elide: Text.ElideRight }
                        Label { text: modelData.value; color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
            }
        }
    }
}
