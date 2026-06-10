import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"

Item {
    id: performanceTab
    property var controller
    property var theme
    property var rootWindow

    function trx(arText, enText) { return controller ? controller.trx(arText, enText) : enText }
    function modeTitle(mode) {
        if (mode === "classic") return trx("خفيف", "Light")
        if (mode === "hybrid") return trx("حماية محسّنة", "Enhanced protection")
        if (mode === "hybrid_accelerated") return trx("حماية محسّنة أسرع", "Faster enhanced")
        return trx("ذكي (موصى به)", "Smart (recommended)")
    }
    function modeDescription(mode) {
        if (mode === "classic") return trx("أقل استهلاكًا للجهاز ويعتمد على المحرك الأساسي فقط.", "Lowest device usage and uses the core engine only.")
        if (mode === "hybrid") return trx("يضيف تحليلًا سلوكيًا أعمق وقد يستهلك موارد أكثر.", "Adds deeper behavior analysis and may use more resources.")
        if (mode === "hybrid_accelerated") return trx("يحاول استخدام نفس التحليل المحسن عبر مسار أسرع إذا كان متاحًا.", "Tries the same enhanced analysis through a faster path when available.")
        return trx("يدع BioAuth يختار الوضع الأنسب بناءً على فحص الجهاز.", "Lets BioAuth choose the best safe mode based on your device check.")
    }
    function modeHelp(mode) {
        if (mode === "classic") return trx("اختر هذا إذا أردت أقل حمل ممكن على الجهاز. مناسب للأجهزة الأضعف أو إذا كنت تفضّل الاستقرار أولًا.", "Choose this for the lowest system load. Best for weaker devices or when you want stability first.")
        if (mode === "hybrid") return trx("يضيف طبقة تحليل إضافية لتحسين التمييز بين الاستخدام الطبيعي والسلوك المريب، لكنه قد يرفع استهلاك المعالج والذاكرة قليلًا.", "Adds an extra analysis layer to improve distinction between normal use and suspicious behavior, but it can use a bit more CPU and memory.")
        if (mode === "hybrid_accelerated") return trx("يشبه الحماية المحسّنة، لكنه يحاول استخدام مسار أسرع عند توفره. إذا لم يكن متاحًا سيعود النظام للوضع الآمن تلقائيًا.", "Similar to enhanced protection, but it tries to use a faster path when available. If that path is not available, the app safely falls back automatically.")
        return trx("هذا هو الخيار الأنسب لمعظم الحالات. يوازن بين الدقة والأداء ويعتمد على فحص الجهاز عند الحاجة.", "This is the best choice for most cases. It balances accuracy and performance and uses the device check when needed.")
    }

    readonly property bool benchmarkReady: backend.deepRuntimeBenchmark && backend.deepRuntimeBenchmark.status === "ok"
    readonly property string recommendedMode: backend.deepRuntimeRecommendedMode || "classic"
    readonly property string effectiveMode: backend.deepRuntimeEffectiveMode || "classic"
    readonly property string selectedBackend: backend.deepRuntimeSelectedBackend || "classic"
    readonly property bool isRuntimeFallback: backend.deepRuntimeIsFallback === true
    readonly property string fallbackReasonText: backend.deepRuntimeFallbackReasonText || ""
    readonly property var productionApproval: backend.productionApprovalState || ({})
    readonly property var modelReadiness: backend.modelReadinessState || ({})
    readonly property var shadowLoop: modelReadiness.shadowLoopState || ({})
    readonly property bool shadowAutomationPaused: backend.shadowAutomationPaused === true
    readonly property var effectiveReadyState: backend.effectiveProductionReadyState || ({})
    readonly property var autoPromotion: productionApproval.autoPromotionState || ({})

    function listText(value) {
        if (!value) return "—"
        if (value.join) return value.length > 0 ? value.join(", ") : "—"
        return String(value)
    }
    function metricsText() {
        var metrics = productionApproval.metricValues || ({})
        var parts = []
        if (metrics.auc !== undefined) parts.push("AUC=" + metrics.auc)
        if (metrics.f1 !== undefined) parts.push("F1=" + metrics.f1)
        if (metrics.far !== undefined) parts.push("FAR=" + metrics.far)
        if (metrics.frr !== undefined) parts.push("FRR=" + metrics.frr)
        if (metrics.session_count !== undefined) parts.push("sessions=" + metrics.session_count)
        return parts.length > 0 ? parts.join(" • ") : trx("لا توجد قيم metric دقيقة في الملفات الحالية.", "No exact metric values are present in the current files.")
    }
    function setupSummaryText() {
        if (productionApproval.protectedSessionsAvailable === true)
            return trx("الجلسات المحمية جاهزة لأن النموذج معتمد للإنتاج وحزمة التشغيل صالحة.", "Protected Sessions are ready because the model is production-approved and the runtime bundle is valid.")
        if (shadowLoop.active === true || productionApproval.modelStatus === "approved_for_shadow")
            return trx("BioAuth يتحقق من النموذج بأمان ويجمع تحسينات مستهدفة قبل إعادة التدريب.", "BioAuth is safely validating the model and collecting targeted improvements before retraining.")
        if (modelReadiness.backgroundAction === "training_in_background")
            return trx("التدريب يعمل في الخلفية من مسار backend الحالي.", "Training is running in the background through the existing backend path.")
        return modelReadiness.safeUserMessage || productionApproval.safeRecommendationText || trx("BioAuth سيعرض الخطوة التالية بعد التحديث القادم لحالة backend.", "BioAuth will show the next step after the next backend state refresh.")
    }

    Layout.fillWidth: true
    implicitHeight: performanceContent.implicitHeight

    ColumnLayout {
        id: performanceContent
        width: parent.width
        spacing: 16

        GlassCard {
            Layout.fillWidth: true
            implicitHeight: engineSummaryContent.implicitHeight + 40
            ColumnLayout {
                id: engineSummaryContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 14

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    SectionHeader {
                        Layout.fillWidth: true
                        title: trx("الأداء والحماية", "Performance & protection")
                        subtitle: trx("اختر كيف يوازن BioAuth بين الحمل على الجهاز والتحليل السلوكي الإضافي.", "Choose how BioAuth balances device load with extra behavior analysis.")
                    }
                    ToolButton {
                        text: "?"
                        implicitWidth: 30
                        implicitHeight: 30
                        padding: 0
                        background: Rectangle {
                            radius: width / 2
                            color: theme.surface2
                            border.color: theme.border
                            border.width: 1
                        }
                        contentItem: Label {
                            text: parent.text
                            color: theme.text
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            font.bold: true
                        }
                        ToolTip.visible: hovered
                        ToolTip.text: trx("هذا القسم يحدد إن كان BioAuth يستخدم المحرك الأساسي فقط أو يضيف طبقة تحليل سلوكي أعمق عندما يكون الجهاز مناسبًا.", "This section controls whether BioAuth uses only the core engine or adds a deeper behavior analysis layer when the device is suitable.")
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: width >= 1080 ? 2 : 1
                    columnSpacing: 12
                    rowSpacing: 12

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: statusColumn.implicitHeight + 28
                        radius: 18
                        color: theme.surface1
                        border.color: theme.border
                        border.width: 1
                        ColumnLayout {
                            id: statusColumn
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 6
                            Label { text: trx("الوضع المحدد", "Selected mode"); color: theme.muted; font.bold: true }
                            Label { text: modeTitle(controller.draftDeepRuntimeMode); color: theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { text: modeDescription(controller.draftDeepRuntimeMode); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: runtimeColumn.implicitHeight + 28
                        radius: 18
                        color: theme.surface1
                        border.color: theme.border
                        border.width: 1
                        ColumnLayout {
                            id: runtimeColumn
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 6
                            Label { text: trx("الوضع الفعلي الآن", "Current engine state"); color: theme.muted; font.bold: true }
                            Label { text: modeTitle(effectiveMode); color: theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { text: benchmarkReady ? trx("آخر توصية: ", "Last recommendation: ") + modeTitle(recommendedMode) : trx("لم يتم تشغيل فحص الجهاز بعد.", "Device check has not been run yet."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { text: trx("المسار الحالي: ", "Current backend: ") + selectedBackend; color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { visible: isRuntimeFallback; text: fallbackReasonText; color: theme.warn; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { visible: isRuntimeFallback; text: trx("تبقى الحماية نشطة عبر المحرك الأساسي حتى عندما لا تعمل الحماية المحسّنة.", "Protection remains active through the core engine when enhanced runtime is unavailable."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        }
                    }
                }
            }
        }

        GlassCard {
            Layout.fillWidth: true
            implicitHeight: productionDiagnosticsContent.implicitHeight + 40
            ColumnLayout {
                id: productionDiagnosticsContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 14

                SectionHeader {
                    title: trx("تشخيص متقدم", "Advanced diagnostics")
                    subtitle: trx("تفاصيل تقنية من النظام فقط. الشاشة المبسطة تعرض الحالة العامة، وهذه المنطقة تحتفظ بالمسارات والبوابات والـ fallback.", "Technical system-only details. The simplified view shows general status, while this area keeps paths, gates, and fallback data.")
                }

                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    color: theme.text
                    font.bold: true
                    text: setupSummaryText()
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: width >= 1080 ? 2 : 1
                    columnSpacing: 12
                    rowSpacing: 12

                    Repeater {
                        model: [
                            { label: trx("Model status", "Model status"), value: productionApproval.modelStatus || "untrained", tone: productionApproval.protectedSessionsAvailable === true ? "success" : (productionApproval.modelStatus === "approved_for_shadow" ? "warn" : "details") },
                            { label: trx("Protected Sessions", "Protected Sessions"), value: productionApproval.protectedSessionsAvailable === true ? trx("متاحة", "Available") : trx("مقفلة", "Locked"), tone: productionApproval.protectedSessionsAvailable === true ? "success" : "warn" },
                            { label: trx("Auto promotion", "Auto promotion"), value: autoPromotion.enabled === true ? (autoPromotion.lastReason || modelReadiness.backgroundAction || "enabled") : trx("متوقفة", "disabled"), tone: autoPromotion.enabled === true ? "info" : "neutral" },
                            { label: trx("Effective readiness", "Effective readiness"), value: backend.effectiveProductionReadyLabel || trx("غير جاهز", "not ready"), tone: backend.effectiveProductionReady === true ? (effectiveReadyState.devProductionReadySimulation === true ? "warn" : "success") : "warn" },
                            { label: trx("Shadow automation", "Shadow automation"), value: shadowAutomationPaused ? trx("متوقف يدويًا", "paused manually") : trx("مسموح", "allowed"), tone: shadowAutomationPaused ? "warn" : "success" },
                            { label: trx("Shadow loop", "Shadow loop"), value: shadowAutomationPaused ? trx("متوقف يدويًا", "paused manually") : (shadowLoop.active === true ? (shadowLoop.phase || "collecting_targeted_sessions") : trx("غير نشط", "inactive")), tone: shadowAutomationPaused ? "warn" : (shadowLoop.active === true ? "info" : "neutral") },
                            { label: trx("Shadow action", "Shadow action"), value: shadowAutomationPaused ? trx("اختبار classic/hybrid بدون shadow auto-start", "test classic/hybrid without shadow auto-start") : (shadowLoop.targetedCollectionAction || modelReadiness.nextBestAction || "--"), tone: shadowAutomationPaused ? "warn" : (shadowLoop.active === true ? "info" : "details") },
                            { label: trx("Failed gates", "Failed gates"), value: listText(productionApproval.failedProductionGates), tone: "warn" },
                            { label: trx("Active contexts", "Active contexts"), value: listText(productionApproval.activeRoutedContexts), tone: "details" },
                            { label: trx("Evaluation report", "Evaluation report"), value: productionApproval.evaluationReportFile || trx("غير موجود", "not found"), tone: productionApproval.evaluationReportAvailable === true ? "success" : "warn" },
                            { label: trx("Evaluation summary", "Evaluation summary"), value: productionApproval.evaluationSummaryFile || trx("غير موجود", "not found"), tone: productionApproval.evaluationSummaryAvailable === true ? "success" : "details" },
                            { label: trx("Deep runtime mode", "Deep runtime mode"), value: effectiveMode + (isRuntimeFallback ? trx(" · fallback", " · fallback") : ""), tone: isRuntimeFallback ? "warn" : "success" },
                            { label: trx("Fallback reason", "Fallback reason"), value: fallbackReasonText || trx("لا يوجد", "none"), tone: isRuntimeFallback ? "warn" : "details" },
                            { label: trx("Runtime validation", "Runtime validation"), value: productionApproval.runtimeValidationReason || "runtime_pointer_missing", tone: productionApproval.protectedSessionsAvailable === true ? "success" : "warn" }
                        ]
                        delegate: Rectangle {
                            Layout.fillWidth: true
                            radius: 18
                            color: theme.surface1
                            border.color: theme.border
                            border.width: 1
                            implicitHeight: diagTile.implicitHeight + 24
                            ColumnLayout {
                                id: diagTile
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 6
                                Label { text: modelData.label; color: theme.muted; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                InfoPill { textValue: modelData.value; pillTone: modelData.tone }
                            }
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    color: theme.text
                    font.bold: true
                    text: productionApproval.approvalReasonText || trx("لا توجد نتيجة تدريب/تقييم لعرضها بعد.", "No training/evaluation result is available yet.")
                }
                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    color: theme.muted
                    text: trx("القيم الدقيقة: ", "Exact metrics: ") + metricsText()
                }
                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    color: theme.muted
                    text: trx("الإجراء التالي: ", "Next action: ") + (modelReadiness.nextBestAction || productionApproval.backgroundNextAction || "train_when_ready") + " — " + (modelReadiness.advancedDiagnosticText || productionApproval.safeRecommendationText || "")
                }
            }
        }

        GlassCard {
            Layout.fillWidth: true
            visible: backend.uiMode !== "user"
            implicitHeight: visible ? developerShadowContent.implicitHeight + 40 : 0
            ColumnLayout {
                id: developerShadowContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 14

                SectionHeader {
                    Layout.fillWidth: true
                    title: trx("تحكم Shadow المتقدم", "Advanced shadow control")
                    subtitle: trx("أوقف shadow automation مؤقتًا لتجربة monitor على classic و hybrid بدون auto-start لمسار shadow evidence.", "Pause shadow automation while testing the monitor in classic or hybrid without shadow evidence auto-start.")
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: developerShadowStatus.implicitHeight + 28
                    radius: 18
                    color: shadowAutomationPaused ? theme.warningBg : theme.surface1
                    border.color: shadowAutomationPaused ? theme.warn : theme.border
                    border.width: 1
                    ColumnLayout {
                        id: developerShadowStatus
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 8
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            Label {
                                Layout.fillWidth: true
                                text: shadowAutomationPaused ? trx("Shadow متوقف يدويًا", "Shadow is manually paused") : trx("Shadow automation مسموح", "Shadow automation is allowed")
                                color: theme.text
                                font.bold: true
                                wrapMode: Text.Wrap
                            }
                            InfoPill {
                                textValue: shadowAutomationPaused ? trx("PAUSED", "PAUSED") : trx("ACTIVE", "ACTIVE")
                                pillTone: shadowAutomationPaused ? "warn" : "success"
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: shadowAutomationPaused
                                  ? trx("لن يبدأ shadow worker أو shadow evidence monitor تلقائيًا. في العرض المتقدم سيستخدم BioAuth جاهزية إنتاج محاكاة لاختبار classic/hybrid monitor بدون تغيير اعتماد الإنتاج الحقيقي.", "Shadow worker and shadow evidence monitor will not auto-start. In the advanced view, BioAuth uses simulated production-ready status for classic/hybrid monitor tests without changing real production approval.")
                                  : trx("إذا صار candidate approved_for_shadow، يسمح BioAuth بجمع shadow evidence حسب safety gates الحالية.", "If a candidate becomes approved_for_shadow, BioAuth may collect shadow evidence according to the current safety gates.")
                            color: theme.muted
                            wrapMode: Text.Wrap
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    AppButton {
                        text: shadowAutomationPaused ? trx("تشغيل Shadow", "Resume shadow") : trx("إيقاف Shadow", "Pause shadow")
                        role: shadowAutomationPaused ? "primary" : "danger"
                        debugLabel: "developer_shadow_pause_toggle"
                        onClicked: backend.setShadowAutomationPaused(!backend.shadowAutomationPaused)
                    }
                    Label {
                        Layout.fillWidth: true
                        text: backend.effectiveProductionReadyLabel || trx("استخدمها قبل classic / hybrid monitor tests حتى لا يتحول الاختبار لمسار shadow evidence تلقائيًا.", "Use this before classic / hybrid monitor tests so the run does not auto-switch into shadow evidence.")
                        color: theme.muted
                        wrapMode: Text.Wrap
                    }
                }
            }
        }

        GlassCard {
            Layout.fillWidth: true
            implicitHeight: modeChoicesContent.implicitHeight + 40
            ColumnLayout {
                id: modeChoicesContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 14

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    SectionHeader {
                        Layout.fillWidth: true
                        title: trx("وضع الأداء", "Engine mode")
                        subtitle: trx("استخدم اسمًا بسيطًا الآن، وسيُطبَّق الوضع التقني المقابل في الخلفية.", "Pick a simple mode here and BioAuth applies the matching runtime mode in the background.")
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: width >= 1080 ? 2 : 1
                    columnSpacing: 12
                    rowSpacing: 12

                    SelectableInfoCard {
                        theme: performanceTab.theme
                        titleText: modeTitle("auto")
                        descriptionText: modeDescription("auto")
                        helpText: modeHelp("auto")
                        badgeText: trx("AUTO", "AUTO")
                        accentColor: theme.primary
                        selected: controller.draftDeepRuntimeMode === "auto"
                        onChosen: controller.draftDeepRuntimeMode = "auto"
                    }
                    SelectableInfoCard {
                        theme: performanceTab.theme
                        titleText: modeTitle("classic")
                        descriptionText: modeDescription("classic")
                        helpText: modeHelp("classic")
                        badgeText: trx("LITE", "LITE")
                        accentColor: "#06b6d4"
                        selected: controller.draftDeepRuntimeMode === "classic"
                        onChosen: controller.draftDeepRuntimeMode = "classic"
                    }
                    SelectableInfoCard {
                        theme: performanceTab.theme
                        titleText: modeTitle("hybrid")
                        descriptionText: modeDescription("hybrid")
                        helpText: modeHelp("hybrid")
                        badgeText: trx("PLUS", "PLUS")
                        accentColor: theme.accent
                        selected: controller.draftDeepRuntimeMode === "hybrid"
                        onChosen: controller.draftDeepRuntimeMode = "hybrid"
                    }
                    SelectableInfoCard {
                        theme: performanceTab.theme
                        titleText: modeTitle("hybrid_accelerated")
                        descriptionText: modeDescription("hybrid_accelerated")
                        helpText: modeHelp("hybrid_accelerated")
                        badgeText: trx("FAST", "FAST")
                        accentColor: "#22c55e"
                        selected: controller.draftDeepRuntimeMode === "hybrid_accelerated"
                        onChosen: controller.draftDeepRuntimeMode = "hybrid_accelerated"
                    }
                }
            }
        }

        GlassCard {
            Layout.fillWidth: true
            implicitHeight: benchmarkContent.implicitHeight + 40
            ColumnLayout {
                id: benchmarkContent
                anchors.fill: parent
                anchors.margins: 20
                spacing: 14

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    SectionHeader {
                        Layout.fillWidth: true
                        title: trx("فحص الجهاز", "Device check")
                        subtitle: trx("يشغّل اختبارًا محليًا سريعًا لمساعدة BioAuth على اقتراح الوضع الأنسب لهذا الجهاز.", "Runs a short local check so BioAuth can recommend the best mode for this device.")
                    }
                    ToolButton {
                        text: "?"
                        implicitWidth: 30
                        implicitHeight: 30
                        padding: 0
                        background: Rectangle {
                            radius: width / 2
                            color: theme.surface2
                            border.color: theme.border
                            border.width: 1
                        }
                        contentItem: Label {
                            text: parent.text
                            color: theme.text
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            font.bold: true
                        }
                        ToolTip.visible: hovered
                        ToolTip.text: trx("فحص الجهاز لا يرسل بياناتك إلى أي مكان. هو مجرد اختبار محلي قصير لتقدير الأداء واختيار الوضع الأكثر أمانًا وملاءمة.", "The device check does not send your data anywhere. It is only a short local test to estimate performance and choose the safest suitable mode.")
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: benchmarkSummary.implicitHeight + 28
                    radius: 18
                    color: benchmarkReady ? theme.surface1 : theme.warningBg
                    border.color: benchmarkReady ? theme.border : theme.warn
                    border.width: 1
                    ColumnLayout {
                        id: benchmarkSummary
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 6
                        Label { text: benchmarkReady ? trx("آخر نتيجة", "Last result") : trx("لا توجد نتيجة محفوظة بعد", "No saved result yet"); color: theme.text; font.bold: true }
                        Label { text: benchmarkReady ? (trx("الوضع الموصى به: ", "Recommended mode: ") + modeTitle(recommendedMode)) : trx("شغّل فحص الجهاز مرة واحدة لتحصل على توصية مناسبة.", "Run the device check once to get a suitable recommendation."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: benchmarkReady ? (trx("المسار المقترح: ", "Suggested backend: ") + selectedBackend) : trx("يمكنك أيضًا اختيار الوضع يدويًا إذا كنت تعرف ما تفضله.", "You can still choose a mode manually if you know what you prefer."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    AppButton {
                        text: benchmarkReady ? trx("إعادة فحص الجهاز", "Run device check again") : trx("تشغيل فحص الجهاز", "Run device check")
                        role: "primary"
                        onClicked: backend.runDeepRuntimeBenchmark()
                    }
                    AppButton {
                        text: trx("استخدام الإعداد الموصى به", "Use recommended setup")
                        role: "neutral"
                        enabled: benchmarkReady
                        onClicked: controller.draftDeepRuntimeMode = "auto"
                    }
                    AppButton {
                        text: trx("مسح نتيجة الفحص", "Clear saved check")
                        role: "neutral"
                        enabled: benchmarkReady
                        onClicked: backend.clearDeepRuntimeBenchmark()
                    }
                }
            }
        }
    }
}
