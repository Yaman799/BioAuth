import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property bool compactLayout: rootWindow ? rootWindow.compactLayout : width < 1180
    readonly property var productionApproval: backend.productionApprovalState || ({})
    readonly property var autoEnrollment: backend.autoEnrollmentState || ({})
    readonly property var modelReadiness: backend.modelReadinessState || ({})
    readonly property var shadowLoop: modelReadiness.shadowLoopState || ({})
    readonly property var autoPromotion: productionApproval.autoPromotionState || ({})

    function trx(arText, enText) { return rootWindow ? rootWindow.trx(arText, enText) : enText }
    function trainingProgressText() {
        if (backend.profile.ready)
            return backend.tr("guide_ready")
        if (backend.profile.training_can_start)
            return backend.tr("guide_training_ready")
        if ((backend.profile.training_block_reason || "") === "need_higher_quality_sessions")
            return backend.tr("training_need_higher_quality_sessions")
        return backend.tr("guide_not_ready").replace("{remaining}", Math.max(0, Number(backend.minEnrollmentText) - (backend.profile.session_count || 0)))
    }
    function trustedSessionNote() {
        var trusted = Number(backend.profile.session_count || 0)
        var saved = Number(backend.profile.saved_session_count || trusted)
        if (saved > trusted) {
            return trx("المحفوظ الشرعي: ", "Saved legit enrollment sessions: ") + String(saved)
                 + trx(" • المعتمد للتدريب: ", " • Trusted for training: ") + String(trusted)
        }
        return ""
    }
    function trainingProgressParams() {
        return backend.trainingProgress && backend.trainingProgress.message_params ? backend.trainingProgress.message_params : ({})
    }
    function heartbeatText() {
        var seconds = Number(trainingProgressParams().heartbeat_seconds || 0)
        if (!backend.trainingInProgress || seconds <= 0)
            return ""
        return trx("ما زال التدريب يعمل... " + String(seconds) + "ث", "Still running... " + String(seconds) + "s")
    }
    function positiveSessionsText() {
        var count = Number(trainingProgressParams().positive_sessions || 0)
        if (count <= 0)
            return ""
        return trx("الجلسات الإيجابية: ", "Positive sessions: ") + String(count)
    }
    function referenceNegativesText() {
        var count = Number(trainingProgressParams().reference_negatives || 0)
        if (count <= 0)
            return ""
        return trx("المرجعيات السلبية: ", "Reference negatives: ") + String(count)
    }
    readonly property string heartbeatSummary: heartbeatText()
    readonly property string positiveSessionsSummary: positiveSessionsText()
    readonly property string referenceNegativesSummary: referenceNegativesText()
    function stageTone(stage) {
        if (stage === "collect")
            return Number(backend.profile.session_count || 0) >= Number(backend.minEnrollmentText || 8) ? "success" : "warn"
        if (stage === "train")
            return backend.profile.training_can_start ? "success" : "details"
        return backend.profile.ready ? "success" : "neutral"
    }
    function stageText(stage) {
        if (stage === "collect")
            return trx("جلسات التهيئة", "Enrollment sessions") + ": " + String(backend.profile.session_count || 0)
        if (stage === "train")
            return backend.profile.training_can_start ? trx("أصبح التدريب متاحًا", "Training is unlocked") : trx("بانتظار الحد الأدنى والجودة", "Waiting for minimum and quality gates")
        return backend.profile.ready ? trx("الحماية الجارية مدعومة بالملف", "Protection is backed by the profile") : trx("الحماية الكاملة تنتظر جاهزية الملف", "Full protection is waiting for profile readiness")
    }
    function nextMilestoneTitle() {
        if (productionApproval.protectedSessionsAvailable === true)
            return trx("الجلسات المحمية جاهزة", "Protected Sessions are ready")
        if (shadowLoop.active === true)
            return trx("BioAuth يتحقق من النموذج بأمان", "BioAuth is validating the model safely")
        if (modelReadiness.readinessLevel === "targeted_collection")
            return trx("BioAuth يحسن نموذج الحماية", "BioAuth is improving the protection model")
        if (productionApproval.modelStatus === "approved_for_shadow")
            return trx("النموذج في تحقق آمن", "Model is in safe validation")
        if (backend.profile.ready)
            return trx("تم تدريب الملف وينتظر اعتماد الإنتاج", "Profile trained; production approval pending")
        if (backend.profile.training_can_start)
            return trx("الخطوة التالية: تدريب الملف", "Next step: train the profile")
        return trx("الخطوة التالية: جمع جلسات موثوقة أكثر", "Next step: collect more trusted sessions")
    }
    function nextMilestoneBody() {
        if (productionApproval.protectedSessionsAvailable === true)
            return trx("نجح النموذج في اعتماد الإنتاج وتم التحقق من حزمة التشغيل.", "The model passed production approval and the runtime bundle is verified.")
        if (shadowLoop.active === true)
            return (shadowLoop.safeUserMessage || trx("BioAuth يتحقق من نموذج الحماية بأمان في الخلفية.", "BioAuth is validating your protection model safely in the background.")) + " " + (shadowLoop.targetedCollectionText || "")
        if (modelReadiness.safeUserMessage && productionApproval.protectedSessionsAvailable !== true)
            return modelReadiness.safeUserMessage + " " + (modelReadiness.nextBestActionText || "")
        if (productionApproval.modelStatus === "approved_for_shadow")
            return productionApproval.approvalReasonText || trx("النموذج مناسب للتحقق في الخلفية فقط، لذلك تبقى الجلسات المحمية مقفلة حتى يجتاز اعتماد الإنتاج.", "The model is suitable for background validation only, so Protected Sessions stay locked until production approval passes.")
        if (backend.profile.ready)
            return productionApproval.safeRecommendationText || trx("لا يتم فتح الجلسات المحمية إلا بعد اجتياز اعتماد الإنتاج والتحقق من حزمة التشغيل.", "Protected Sessions unlock only after production approval and runtime bundle validation pass.")
        if (backend.profile.training_can_start)
            return backend.tr("guide_training_ready")
        return trainingProgressText()
    }
    function productionStatusLabel() {
        if (productionApproval.protectedSessionsAvailable === true)
            return trx("متاحة", "Available")
        if (productionApproval.modelStatus === "approved_for_shadow")
            return trx("Shadow فقط", "Shadow only")
        if (productionApproval.modelStatus === "approved_for_production")
            return trx("اعتماد الإنتاج ينتظر runtime", "Production-approved; runtime pending")
        if (backend.profile.ready)
            return trx("مقفلة", "Locked")
        return trx("بانتظار التدريب", "Waiting for training")
    }
    function productionStatusTone() {
        if (productionApproval.protectedSessionsAvailable === true) return "success"
        if (productionApproval.modelStatus === "approved_for_shadow") return "warn"
        if (productionApproval.modelStatus === "approved_for_production") return "info"
        return backend.profile.ready ? "warn" : "neutral"
    }
    function setupJourneyStage() {
        if (productionApproval.protectedSessionsAvailable === true)
            return "protected_ready"
        if (autoEnrollment.backgroundAction === "training_in_background" || modelReadiness.backgroundAction === "training_in_background" || backend.trainingInProgress)
            return "training_background"
        if (shadowLoop.active === true)
            return "shadow_validating"
        if (modelReadiness.readinessLevel === "targeted_collection" || modelReadiness.nextBestAction === "collect_keyboard_mixed_sessions" || modelReadiness.nextBestAction === "collect_diverse_high_quality_sessions")
            return "targeted_improvements"
        if (productionApproval.modelStatus === "approved_for_shadow")
            return "shadow_validating"
        if (autoEnrollment.trainingReady === true || backend.profile.training_can_start === true)
            return "ready_to_train"
        if (autoEnrollment.collecting === true)
            return "collecting_natural_sessions"
        if (autoEnrollment.enabled === true)
            return "learning_behavior"
        if (productionApproval.protectedSessionsAvailable !== true && (productionApproval.approvalReasonText || productionApproval.safeRecommendationText))
            return "protected_blocked"
        return "learning_behavior"
    }
    function setupJourneyTitle() {
        var stage = setupJourneyStage()
        if (stage === "protected_ready") return trx("الجلسات المحمية جاهزة", "Protected Sessions are ready")
        if (stage === "training_background") return trx("يجري تدريب نموذج الحماية", "Training your protection model")
        if (stage === "shadow_validating") return trx("تحقق آمن في الخلفية", "Safe background validation")
        if (stage === "targeted_improvements") return trx("تحسينات مستهدفة قيد الجمع", "Collecting targeted improvements")
        if (stage === "ready_to_train") return trx("جاهز للتدريب", "Ready to train")
        if (stage === "collecting_natural_sessions") return trx("يجمع جلسات طبيعية", "Collecting natural sessions")
        if (stage === "protected_blocked") return trx("الجلسات المحمية مقفلة بأمان", "Protected Sessions are safely locked")
        return trx("يتعلم سلوكك الطبيعي", "Learning your behavior")
    }
    function setupJourneyBody() {
        var stage = setupJourneyStage()
        if (stage === "protected_ready")
            return productionApproval.safeRecommendationText || trx("اجتاز النموذج اعتماد الإنتاج وتم التحقق من runtime. يمكنك بدء الجلسات المحمية الآن.", "Your model passed production approval and runtime validation. You can start Protected Sessions now.")
        if (stage === "training_background")
            return trx("BioAuth يدرب نموذج الحماية في الخلفية. يمكنك متابعة استخدام الجهاز، وستبقى الجلسات المحمية مقفلة حتى ينجح اعتماد الإنتاج.", "BioAuth is training your protection model in the background. You can keep using your device; Protected Sessions stay locked until production approval passes.")
        if (stage === "shadow_validating")
            return (shadowLoop.safeUserMessage || modelReadiness.safeUserMessage || trx("BioAuth يتحقق من نموذج الحماية بأمان في الخلفية.", "BioAuth is validating your protection model safely in the background.")) + " " + (shadowLoop.targetedCollectionText || modelReadiness.nextBestActionText || productionApproval.safeRecommendationText || "")
        if (stage === "targeted_improvements")
            return modelReadiness.safeUserMessage || modelReadiness.nextBestActionText || trx("BioAuth سيجمع جلسات أفضل وأكثر توازنًا قبل إعادة التدريب.", "BioAuth will collect better, more balanced sessions before retraining.")
        if (stage === "ready_to_train")
            return autoEnrollment.autoTrainingEnabled === true
                   ? trx("تم الوصول إلى الجاهزية، وسيبدأ التدريب الخلفي عندما تكون الحالة آمنة ولا توجد مهمة جارية.", "Readiness is reached, and background training will start when the app is safe and no job is active.")
                   : trx("تم جمع جلسات كافية. يمكنك تشغيل التدريب يدويًا أو تفعيل التدريب التلقائي من الإعدادات.", "Enough sessions are collected. You can train manually or enable automatic training in settings.")
        if (stage === "collecting_natural_sessions")
            return autoEnrollment.collectionStatusText || trx("BioAuth يجمع جلسات تهيئة طبيعية بعد موافقتك الصريحة.", "BioAuth is collecting natural enrollment sessions after your explicit consent.")
        if (stage === "protected_blocked")
            return productionApproval.approvalReasonText || productionApproval.safeRecommendationText || trx("لن تُفتح الجلسات المحمية حتى يجتاز النموذج اعتماد الإنتاج والتحقق من حزمة runtime.", "Protected Sessions will not unlock until the model passes production approval and runtime bundle validation.")
        if (autoEnrollment.consentSatisfied !== true)
            return trx("التعلم التلقائي يحتاج موافقة خصوصية واضحة قبل أي جمع للبيانات السلوكية.", "Automatic learning needs explicit privacy consent before any behavioral data collection.")
        return autoEnrollment.collectionStatusText || trx("BioAuth يجهز تجربة الحماية الآلية بدون وعود قبل اعتماد الإنتاج.", "BioAuth is preparing the automated protection setup without promising production protection early.")
    }
    function setupJourneyTone() {
        var stage = setupJourneyStage()
        if (stage === "protected_ready") return "success"
        if (stage === "protected_blocked" || productionApproval.modelStatus === "approved_for_shadow") return "warn"
        if (stage === "training_background" || stage === "shadow_validating" || stage === "targeted_improvements") return "info"
        if (stage === "ready_to_train") return "success"
        if (stage === "collecting_natural_sessions" || stage === "learning_behavior") return autoEnrollment.consentSatisfied === true ? "info" : "warn"
        return "details"
    }
    function setupJourneyStepPills() {
        return [
            { label: trx("Learning", "Learning"), active: setupJourneyStage() === "learning_behavior" || setupJourneyStage() === "collecting_natural_sessions", tone: autoEnrollment.collecting === true ? "success" : (autoEnrollment.enabled === true ? "info" : "neutral") },
            { label: trx("Ready", "Ready"), active: autoEnrollment.trainingReady === true || backend.profile.training_can_start === true, tone: (autoEnrollment.trainingReady === true || backend.profile.training_can_start === true) ? "success" : "neutral" },
            { label: trx("Training", "Training"), active: setupJourneyStage() === "training_background", tone: setupJourneyStage() === "training_background" ? "info" : "neutral" },
            { label: trx("Validation", "Validation"), active: shadowLoop.active === true || productionApproval.modelStatus === "approved_for_shadow", tone: (shadowLoop.active === true || productionApproval.modelStatus === "approved_for_shadow") ? "warn" : "neutral" },
            { label: trx("Protected", "Protected"), active: productionApproval.protectedSessionsAvailable === true, tone: productionApproval.protectedSessionsAvailable === true ? "success" : "neutral" }
        ]
    }
    anchors.fill: parent

    ScrollView {
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        Item {
            width: parent.width
            implicitHeight: profileColumn.implicitHeight + 20

            ColumnLayout {
                id: profileColumn
                width: parent.width
                spacing: 18

                Rectangle {
                    visible: backend.trainingInProgress
                    Layout.fillWidth: true
                    radius: 20
                    color: theme.surface4
                    border.color: theme.border
                    border.width: 1
                    implicitHeight: liveTrainingColumn.implicitHeight + 26

                    ColumnLayout {
                        id: liveTrainingColumn
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: 10

                        SectionHeader {
                            title: trx("التدريب الجاري الآن", "Training in progress")
                            subtitle: trx("هذه النسبة قادمة من الـ backend حسب المرحلة الفعلية الجارية الآن.", "This percentage comes from the backend based on the real active training stage.")
                        }

                        Label {
                            text: backend.trainingProgress.headline || backend.tr("training_wait")
                            color: theme.text
                            font.bold: true
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }

                        ProgressTrack {
                            Layout.fillWidth: true
                            value: Number(backend.trainingProgress.percent || 0)
                            maximum: 100
                            fillColor: theme.info
                        }

                        Flow {
                            Layout.fillWidth: true
                            spacing: 10
                            visible: positiveSessionsSummary.length > 0 || referenceNegativesSummary.length > 0

                            InfoPill {
                                visible: positiveSessionsSummary.length > 0
                                textValue: positiveSessionsSummary
                                pillTone: "success"
                            }

                            InfoPill {
                                visible: referenceNegativesSummary.length > 0
                                textValue: referenceNegativesSummary
                                pillTone: "details"
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12

                            Label {
                                text: backend.trainingProgress.detail || ""
                                color: theme.muted
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }

                            InfoPill {
                                textValue: String(backend.trainingProgress.percent || 0) + "%"
                                pillTone: "info"
                            }
                        }

                        Label {
                            visible: heartbeatSummary.length > 0
                            text: heartbeatSummary
                            color: theme.muted
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }
                }

                GlassCard {
                    Layout.fillWidth: true
                    implicitHeight: setupJourneyColumn.implicitHeight + 44

                    ColumnLayout {
                        id: setupJourneyColumn
                        anchors.fill: parent
                        anchors.margins: 22
                        spacing: 12

                        SectionHeader {
                            title: trx("رحلة إعداد الحماية", "Automated protection setup")
                            subtitle: trx("ملخص بسيط من حالات backend الفعلية: التعلم، التدريب، التحقق، ثم فتح الجلسات المحمية فقط عند اعتماد الإنتاج.", "A simple summary from real backend states: learning, training, validation, then Protected Sessions only after production approval.")
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            radius: 18
                            color: theme.surface1
                            border.color: rootWindow ? rootWindow.toneColor(setupJourneyTone()) : theme.border
                            border.width: 1
                            implicitHeight: setupJourneyHero.implicitHeight + 26

                            ColumnLayout {
                                id: setupJourneyHero
                                anchors.fill: parent
                                anchors.margins: 13
                                spacing: 9
                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 10
                                    Label {
                                        text: setupJourneyTitle()
                                        color: theme.text
                                        font.bold: true
                                        font.pixelSize: 19
                                        wrapMode: Text.Wrap
                                        Layout.fillWidth: true
                                    }
                                    InfoPill {
                                        textValue: productionApproval.protectedSessionsAvailable === true ? trx("جاهزة", "Ready") : productionStatusLabel()
                                        pillTone: setupJourneyTone()
                                    }
                                }
                                Label {
                                    text: setupJourneyBody()
                                    color: theme.muted
                                    wrapMode: Text.Wrap
                                    Layout.fillWidth: true
                                }
                            }
                        }

                        Flow {
                            Layout.fillWidth: true
                            spacing: 10
                            Repeater {
                                model: setupJourneyStepPills()
                                delegate: InfoPill {
                                    textValue: (modelData.active ? "✓ " : "") + modelData.label
                                    pillTone: modelData.tone
                                }
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            color: theme.muted
                            text: trx("خصوصيتك تبقى واضحة: الجمع التلقائي يظهر هنا ولا يبدأ بدون الموافقة، والتفاصيل التقنية تبقى في التشخيص المتقدم.", "Privacy stays visible: automatic collection is shown here and never starts without consent; technical details remain in advanced diagnostics.")
                        }
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: root.compactLayout ? 1 : 2
                    columnSpacing: 18
                    rowSpacing: 18

                    GlassCard {
                        Layout.fillWidth: true
                        implicitHeight: identityColumn.implicitHeight + 44

                        ColumnLayout {
                            id: identityColumn
                            anchors.fill: parent
                            anchors.margins: 22
                            spacing: 10
                            SectionHeader {
                                title: trx("Identity profile", "Identity profile")
                                subtitle: trx("ملف الحساب والحالة الحالية لجهوزية النظام.", "Account profile and current system readiness.")
                            }
                            Label { text: trx("Display name", "Display name") + ": " + (backend.currentUser.display_name || "—"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { text: backend.tr("username") + ": " + (backend.currentUser.user_id || "—"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { text: backend.tr("created_at") + ": " + (backend.currentUser.created_at || "—"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            InfoPill {
                                textValue: backend.profile.ready ? trx("Behavioral profile ready", "Behavioral profile ready") : trx("Behavioral profile still learning", "Behavioral profile still learning")
                                pillTone: backend.profile.ready ? "success" : "warn"
                            }
                        }
                    }

                    GlassCard {
                        Layout.fillWidth: true
                        implicitHeight: enrollmentColumn.implicitHeight + 44

                        ColumnLayout {
                            id: enrollmentColumn
                            anchors.fill: parent
                            anchors.margins: 22
                            spacing: 12
                            SectionHeader {
                                title: trx("Enrollment progress", "Enrollment progress")
                                subtitle: trx("من 8 إلى 15 جلسة جيدة لبناء أول ملف قوي.", "Use 8 to 15 good enrollment sessions for a strong first profile.")
                            }
                            Label {
                                text: backend.profile.progressText || ""
                                color: theme.text
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                            ProgressTrack {
                                Layout.fillWidth: true
                                value: backend.profile.session_count || 0
                                maximum: Number(backend.maxEnrollmentText)
                                fillColor: backend.profile.ready ? theme.success : theme.primary
                            }
                            Label {
                                text: trainingProgressText()
                                color: theme.muted
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                            Label {
                                visible: !!trustedSessionNote()
                                text: trustedSessionNote()
                                color: theme.muted
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                        }
                    }

                    GlassCard {
                        Layout.fillWidth: true
                        implicitHeight: smartEnrollmentColumn.implicitHeight + 44

                        ColumnLayout {
                            id: smartEnrollmentColumn
                            anchors.fill: parent
                            anchors.margins: 22
                            spacing: 12

                            SectionHeader {
                                title: trx("Smart Auto Enrollment", "Smart Auto Enrollment")
                                subtitle: trx("BioAuth يتعلم سلوكك الطبيعي بعد الموافقة، ويشغّل التدريب الخلفي فقط عندما تكون الجاهزية آمنة.", "BioAuth learns your natural behavior after consent and runs background training only when readiness is safe.")
                            }

                            Flow {
                                Layout.fillWidth: true
                                spacing: 10
                                InfoPill { textValue: autoEnrollment.enabled === true ? trx("Enabled", "Enabled") : trx("Disabled", "Disabled"); pillTone: autoEnrollment.enabled === true ? "info" : "neutral" }
                                InfoPill { textValue: autoEnrollment.consentSatisfied === true ? trx("Consent OK", "Consent OK") : trx("Consent required", "Consent required"); pillTone: autoEnrollment.consentSatisfied === true ? "success" : "warn" }
                                InfoPill { textValue: autoEnrollment.collecting === true ? trx("Collecting", "Collecting") : trx("Not collecting", "Not collecting"); pillTone: autoEnrollment.collecting === true ? "success" : "neutral" }
                            }

                            Label {
                                text: autoEnrollment.collectionStatusText || trx("Smart Auto Enrollment status will appear here after backend refresh.", "Smart Auto Enrollment status will appear here after backend refresh.")
                                color: theme.text
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }

                            GridLayout {
                                objectName: "profileSmartAutoEnrollmentControls"
                                Layout.fillWidth: true
                                columns: root.compactLayout ? 1 : 3
                                columnSpacing: 10
                                rowSpacing: 10

                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: profileSmartAutoToggleRow.implicitHeight + 24
                                    radius: 16
                                    color: theme.surface1
                                    border.color: autoEnrollment.enabled === true ? theme.info : theme.border
                                    border.width: 1
                                    RowLayout {
                                        id: profileSmartAutoToggleRow
                                        anchors.fill: parent
                                        anchors.margins: 12
                                        spacing: 10
                                        StartupSwitch {
                                            checked: autoEnrollment.enabled === true
                                            debugLabel: "Profile Smart Auto Enrollment"
                                            onToggled: function(nextChecked) { backend.setSmartAutoEnrollmentEnabled(nextChecked) }
                                        }
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 3
                                            Label { text: trx("Smart Auto Enrollment", "Smart Auto Enrollment"); color: theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                            Label { text: trx("يتطلب موافقة خصوصية صريحة.", "Requires explicit privacy consent."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                        }
                                    }
                                }

                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: profileAutoTrainToggleRow.implicitHeight + 24
                                    radius: 16
                                    color: theme.surface1
                                    border.color: autoEnrollment.autoTrainingEnabled === true ? theme.info : theme.border
                                    border.width: 1
                                    RowLayout {
                                        id: profileAutoTrainToggleRow
                                        anchors.fill: parent
                                        anchors.margins: 12
                                        spacing: 10
                                        StartupSwitch {
                                            checked: autoEnrollment.autoTrainingEnabled === true
                                            debugLabel: "Profile Auto Train When Ready"
                                            onToggled: function(nextChecked) { backend.setAutoTrainWhenReadyEnabled(nextChecked) }
                                        }
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 3
                                            Label { text: trx("Auto-train when ready", "Auto-train when ready"); color: theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                            Label { text: trx("يستخدم مسار التدريب الحالي عند الجاهزية.", "Uses the existing training path when ready."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                        }
                                    }
                                }

                                Rectangle {
                                    Layout.fillWidth: true
                                    implicitHeight: profileAutoPromoteToggleRow.implicitHeight + 24
                                    radius: 16
                                    color: theme.surface1
                                    border.color: autoEnrollment.autoPromotionEnabled === true ? theme.info : theme.border
                                    border.width: 1
                                    RowLayout {
                                        id: profileAutoPromoteToggleRow
                                        anchors.fill: parent
                                        anchors.margins: 12
                                        spacing: 10
                                        StartupSwitch {
                                            checked: autoEnrollment.autoPromotionEnabled === true
                                            debugLabel: "Profile Auto Promote When Safe"
                                            onToggled: function(nextChecked) { backend.setAutoPromoteWhenProductionSafeEnabled(nextChecked) }
                                        }
                                        ColumnLayout {
                                            Layout.fillWidth: true
                                            spacing: 3
                                            Label { text: trx("Auto-promote when safe", "Auto-promote when safe"); color: theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                            Label { text: trx("لا يفتح الجلسات المحمية لموديل shadow-only.", "Never unlocks Protected Sessions for a shadow-only model."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                        }
                                    }
                                }
                            }

                            ProgressTrack {
                                Layout.fillWidth: true
                                value: Number(autoEnrollment.acceptedSessions || 0)
                                maximum: Math.max(1, Number(autoEnrollment.recommendedSessions || backend.maxEnrollmentText || 15))
                                fillColor: autoEnrollment.trainingReady === true ? theme.success : theme.primary
                            }

                            Flow {
                                Layout.fillWidth: true
                                spacing: 10
                                InfoPill { textValue: trx("Accepted", "Accepted") + ": " + String(autoEnrollment.acceptedSessions || 0) + " / " + String(autoEnrollment.requiredSessions || backend.minEnrollmentText || 8); pillTone: autoEnrollment.trainingReady === true ? "success" : "warn" }
                                InfoPill { textValue: trx("Keyboard", "Keyboard") + ": " + String((autoEnrollment.inputCoverage && autoEnrollment.inputCoverage.keyboard) || "none"); pillTone: "details" }
                                InfoPill { textValue: trx("Mouse", "Mouse") + ": " + String((autoEnrollment.inputCoverage && autoEnrollment.inputCoverage.mouse) || "none"); pillTone: "details" }
                            }

                            Label {
                                visible: autoEnrollment.backgroundAction === "training_in_background" || modelReadiness.backgroundAction === "training_in_background"
                                text: trx("BioAuth يدرب نموذج الحماية في الخلفية الآن.", "Training your protection model in the background.")
                                color: theme.info
                                font.bold: true
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }

                            Label {
                                text: autoEnrollment.nextBestActionText || trx("Keep using your device normally when Smart Auto Enrollment is enabled.", "Keep using your device normally when Smart Auto Enrollment is enabled.")
                                color: theme.muted
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                        }
                    }
                }

                GlassCard {
                    Layout.fillWidth: true
                    implicitHeight: productionApprovalColumn.implicitHeight + 44

                    ColumnLayout {
                        id: productionApprovalColumn
                        anchors.fill: parent
                        anchors.margins: 22
                        spacing: 12

                        SectionHeader {
                            title: trx("حالة الجلسات المحمية", "Protected Sessions status")
                            subtitle: trx("هذه القراءة تأتي من الـ backend ولا تتجاوز اعتماد الإنتاج أو تحقق runtime.", "This state comes from the backend and does not bypass production approval or runtime validation.")
                        }

                        Flow {
                            Layout.fillWidth: true
                            spacing: 10
                            InfoPill { textValue: productionStatusLabel(); pillTone: productionStatusTone() }
                            InfoPill { textValue: String(productionApproval.modelStatus || trx("غير مدرب", "untrained")); pillTone: productionStatusTone() }
                            InfoPill { textValue: autoPromotion.enabled === true ? trx("ترقية تلقائية آمنة", "Safe auto-promotion on") : trx("ترقية تلقائية متوقفة", "Auto-promotion off"); pillTone: autoPromotion.enabled === true ? "info" : "neutral" }
                            InfoPill { textValue: shadowLoop.active === true ? trx("تحقق خلفي آمن", "Safe background validation") : trx("Shadow loop غير نشط", "Shadow loop inactive"); pillTone: shadowLoop.active === true ? "info" : "neutral" }
                        }

                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            color: theme.text
                            font.bold: true
                            text: productionApproval.protectedSessionsAvailable === true
                                  ? trx("يمكنك بدء الجلسات المحمية الآن.", "You can start Protected Sessions now.")
                                  : trx("الجلسات المحمية مقفلة حاليًا.", "Protected Sessions are currently locked.")
                        }

                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            color: theme.muted
                            text: productionApproval.approvalReasonText || trx("سيعرض BioAuth السبب بعد أول تدريب وتقييم.", "BioAuth will show the reason after the first training and evaluation.")
                        }

                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            color: theme.muted
                            text: trx("الخطوة التالية: ", "Next action: ") + (shadowLoop.active === true ? (shadowLoop.targetedCollectionText || modelReadiness.nextBestActionText || "") : (productionApproval.safeRecommendationText || trx("اجمع جلسات موثوقة ثم درّب الملف.", "Collect trusted sessions, then train the profile.")))
                        }
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: root.compactLayout ? 1 : 2
                    columnSpacing: 18
                    rowSpacing: 18

                    GlassCard {
                        Layout.fillWidth: true
                        implicitHeight: roadmapColumn.implicitHeight + 44

                        ColumnLayout {
                            id: roadmapColumn
                            anchors.fill: parent
                            anchors.margins: 22
                            spacing: 12

                            SectionHeader {
                                title: trx("Readiness roadmap", "Readiness roadmap")
                                subtitle: trx("بديل أوضح من Training Center: يشرح أين وصل الملف وما المرحلة التالية.", "A clearer replacement for the Training Center: where the profile stands and what comes next.")
                            }

                            Repeater {
                                model: [
                                    { title: trx("1) Collect baseline", "1) Collect baseline"), stage: "collect" },
                                    { title: trx("2) Unlock training", "2) Unlock training"), stage: "train" },
                                    { title: trx("3) Run protected mode", "3) Run protected mode"), stage: "protect" }
                                ]

                                delegate: Rectangle {
                                    Layout.fillWidth: true
                                    radius: 18
                                    color: theme.surface4
                                    border.color: theme.border
                                    border.width: 1
                                    implicitHeight: stageColumn.implicitHeight + 24

                                    ColumnLayout {
                                        id: stageColumn
                                        anchors.fill: parent
                                        anchors.margins: 12
                                        spacing: 8
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Label { text: modelData.title; color: theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                            InfoPill { textValue: stageText(modelData.stage); pillTone: stageTone(modelData.stage) }
                                        }
                                    }
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                radius: 18
                                color: theme.surface1
                                border.color: theme.border
                                border.width: 1
                                implicitHeight: milestoneColumn.implicitHeight + 24
                                ColumnLayout {
                                    id: milestoneColumn
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 8
                                    Label { text: nextMilestoneTitle(); color: theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    Label { text: nextMilestoneBody(); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                }
                            }
                        }
                    }

                    GlassCard {
                        Layout.fillWidth: true
                        implicitHeight: compositionColumn.implicitHeight + 44

                        ColumnLayout {
                            id: compositionColumn
                            anchors.fill: parent
                            anchors.margins: 22
                            spacing: 12

                            SectionHeader {
                                title: trx("Profile composition", "Profile composition")
                                subtitle: trx("يوضح من أين تأتي قوة الملف الحالي وما الذي ما زال ينقصه.", "Shows where the current profile draws its strength from and what it still needs.")
                            }

                            GridLayout {
                                Layout.fillWidth: true
                                columns: width >= 420 ? 2 : 1
                                columnSpacing: 12
                                rowSpacing: 12

                                Repeater {
                                    model: [
                                        { title: trx("Trusted enrollment", "Trusted enrollment"), value: String(backend.profile.session_count || 0), tone: backend.profile.session_count >= Number(backend.minEnrollmentText || 8) ? "success" : "warn" },
                                        { title: trx("Saved legit sessions", "Saved legit sessions"), value: String(backend.profile.saved_session_count || backend.profile.session_count || 0), tone: "details" },
                                        { title: trx("Supplemental protected", "Supplemental protected"), value: String(backend.profile.supplemental_protected_count || 0), tone: backend.profile.supplemental_protected_count > 0 ? "info" : "neutral" },
                                        { title: trx("Shadow phase", "Shadow phase"), value: String(backend.shadowStatus.phase || "collecting"), tone: backend.shadowStatus.promote_suggested ? "success" : (backend.shadowStatus.phase === "evaluating" ? "info" : backend.shadowStatus.phase === "training_pending" ? "warn" : "details") }
                                    ]

                                    delegate: Rectangle {
                                        Layout.fillWidth: true
                                        radius: 18
                                        color: theme.surface4
                                        border.color: theme.border
                                        border.width: 1
                                        implicitHeight: compositionTile.implicitHeight + 24
                                        ColumnLayout {
                                            id: compositionTile
                                            anchors.fill: parent
                                            anchors.margins: 12
                                            spacing: 8
                                            Label { text: modelData.title; color: theme.muted; font.bold: true; Layout.fillWidth: true; wrapMode: Text.Wrap }
                                            InfoPill { textValue: modelData.value; pillTone: modelData.tone }
                                        }
                                    }
                                }
                            }

                            Label {
                                Layout.fillWidth: true
                                wrapMode: Text.Wrap
                                color: theme.muted
                                text: backend.profile.ready
                                      ? trx("التركيز الآن ليس على تكرار التدريب من نفس الشاشة، بل على الحفاظ على جلسات محمية موثوقة تغذي shadow lifecycle بمرور الوقت.", "The focus is no longer repeating the same training controls here, but keeping trusted protected sessions that feed the shadow lifecycle over time.")
                                      : trx("كل جلسة موثوقة إضافية ترفع احتمال فتح التدريب أو تحسين جودة الاختيار داخل مرحلة التدريب.", "Each additional trusted session improves the chance of unlocking training or improving the quality gate during training selection.")
                            }
                        }
                    }
                }
            }
        }
    }
}
