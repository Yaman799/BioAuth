import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property bool compactLayout: rootWindow ? rootWindow.compactLayout : width < 1180
    property bool denseLayout: rootWindow ? rootWindow.denseLayout : width < 980

    function trx(arText, enText) { return rootWindow ? rootWindow.trx(arText, enText) : enText }
    function statusTone() { return backend.runtimeState.statusTone || backend.statusTone }
    function decisionTone() { return backend.runtimeState.trustTone || rootWindow.decisionTone(backend.runtimeState.decisionText) }
    function sessionHeadline() {
        var state = backend.runtimeState || {}
        if (!state.active)
            return trx("الجلسة غير نشطة", "Session is idle")
        if (state.technicalFailure)
            return trx("يحتاج تدخل تقني", "Technical intervention needed")
        if (state.lockSuppressionActive)
            return state.runtimeDisplayText || trx("القفل مؤجل بسياسة الحماية", "Lock delayed by protection policy")
        if (state.awaitingEvidence)
            return state.runtimeDisplayText || trx("النظام يجمع أدلة إضافية", "System is collecting more evidence")
        if (String(state.statusCode || "").toLowerCase() === "verifying_return")
            return trx("يجري التحقق من العودة", "Verifying return")
        return trx("المراقبة الحية مستقرة", "Live monitoring is stable")
    }
    function sessionNarrative() {
        var state = backend.runtimeState || {}
        if (!state.active)
            return trx("ابدأ جلسة محمية لرؤية قرارات الثقة والمخاطر والتشخيصات الحية من نفس الشاشة.", "Start a protected session to see live trust decisions, risk, and diagnostics from one place.")
        if (state.technicalFailure)
            return state.diagnosticText || trx("المراقب أبلغ عن مشكلة تقنية. راجع التشخيص قبل استئناف الاعتماد على الإشارة الحية.", "The monitor reported a technical issue. Review diagnostics before relying on the live signal again.")
        if (state.lockSuppressionActive)
            return state.lockSuppressionReasonText || state.escalationPolicyText || trx("القفل مؤجل بسبب قواعد جودة الأدلة الحالية.", "Locking is delayed by the current evidence-quality rules.")
        if (state.evidenceStallActive)
            return state.evidenceStallReasonText || state.expectedNextWindowHint || trx("ينتظر النظام نافذة سلوك مكتملة.", "BioAuth is waiting for a complete behavior window.")
        if (state.awaitingEvidence)
            return state.evidenceWaitingReasonText || state.escalationPolicyText || state.statusDetail || trx("يتم جمع مزيد من الإشارات قبل تثبيت القرار النهائي.", "More evidence is being collected before the final decision is locked in.")
        return state.statusDetail || state.activeText || trx("القرار الحالي يعتمد على أحدث إيقاع سلوكي ملتقط من الجلسة.", "The current decision is based on the most recent behavioral rhythm captured from this session.")
    }
    function nextStepText() {
        var state = backend.runtimeState || {}
        if (!backend.profile.ready)
            return trx("الأولوية الآن هي إكمال بناء baseline حتى تصبح قرارات الحماية أكثر استقرارًا.", "The priority is finishing the baseline so protection decisions become more stable.")
        if (!state.active)
            return trx("يمكنك تشغيل جلسة محمية من Overview أو Profile عندما تريد مراقبة سلوك حي فعلي.", "You can start a protected session from Overview or Profile whenever you want live monitoring.")
        if (state.technicalFailure)
            return trx("أوقف الجلسة الحالية فقط إذا استمر الخلل أو أثّر على دقة الإشارات.", "Stop the current session only if the issue persists or degrades signal quality.")
        if (state.lockSuppressionActive)
            return state.lockSuppressionReasonText || trx("اترك الجلسة تعمل حتى تتوفر أدلة متابعة أقوى.", "Let the session continue until stronger follow-up evidence is available.")
        if (state.awaitingEvidence)
            return state.evidenceWaitingReasonText || trx("انتظر بضع لحظات حتى تكتمل نافذة القياس بدل تغيير السياق بسرعة.", "Wait briefly for the evidence window to complete instead of changing context too quickly.")
        return trx("اترك الجلسة تعمل بشكل طبيعي. الشاشة الحالية مخصّصة للملاحظة وليست للتدخل المتكرر.", "Let the session continue naturally. This screen is meant for observation, not constant intervention.")
    }
    ListModel {
        id: telemetryListModel
        ListElement { label: ""; value: ""; tone: "details" }
        ListElement { label: ""; value: ""; tone: "details" }
        ListElement { label: ""; value: ""; tone: "details" }
        ListElement { label: ""; value: ""; tone: "details" }
        ListElement { label: ""; value: ""; tone: "details" }
        ListElement { label: ""; value: ""; tone: "details" }
        ListElement { label: ""; value: ""; tone: "details" }
    }

    function refreshTelemetryModel() {
        var state = backend.runtimeState || {}
        telemetryListModel.set(0, { label: trx("Status", "Status"), value: state.runtimeDisplayText || state.statusLabel || state.activeText || backend.tr("status_idle"), tone: statusTone() })
        telemetryListModel.set(1, { label: trx("Flow", "Flow"), value: state.flow || "idle", tone: "details" })
        telemetryListModel.set(2, { label: trx("Decision", "Decision"), value: state.trustLabel || state.decisionLabel || state.decisionText || "—", tone: decisionTone() })
        telemetryListModel.set(3, { label: trx("Risk", "Risk"), value: state.riskText || "--", tone: "warn" })
        telemetryListModel.set(4, { label: trx("Average risk", "Average risk"), value: state.avgRiskText || "--", tone: "info" })
        telemetryListModel.set(5, { label: trx("Elapsed", "Elapsed"), value: state.elapsed || "--", tone: "details" })
        telemetryListModel.set(6, { label: trx("Why no lock?", "Why no lock?"), value: state.lockSuppressionReasonText || state.evidenceStallReasonText || state.evidenceWaitingReasonText || state.escalationPolicyText || state.diagnosticText || state.statusDetail || "--", tone: state.lockSuppressionActive ? "warn" : (state.technicalFailure ? "danger" : "details") })
    }

    Component.onCompleted: refreshTelemetryModel()

    Connections {
        target: backend
        function onRuntimeStateChanged() { root.refreshTelemetryModel() }
        function onLanguageChanged() { root.refreshTelemetryModel() }
    }

    anchors.fill: parent

    ScrollView {
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        Item {
            width: parent.width
            implicitHeight: liveColumn.implicitHeight + 20

            ColumnLayout {
                id: liveColumn
                width: parent.width
                spacing: root.denseLayout ? 14 : 18

                GridLayout {
                LiveTelemetryPanel {
                    rootWindow: root.rootWindow
                    Layout.fillWidth: true
                }

                    Layout.fillWidth: true
                    columns: root.compactLayout ? 1 : 2
                    columnSpacing: 18
                    rowSpacing: 18

                    GlassCard {
                        Layout.fillWidth: true
                        implicitHeight: storyboardColumn.implicitHeight + 44

                        ColumnLayout {
                            id: storyboardColumn
                            anchors.fill: parent
                            anchors.margins: root.denseLayout ? 18 : 24
                            spacing: 14

                            SectionHeader {
                                title: trx("Session storyboard", "Session storyboard")
                                subtitle: trx("قراءة بشرية مبسطة لما يحدث الآن داخل طبقة المراقبة.", "A human-friendly readout of what the monitor layer is doing right now.")
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                radius: 20
                                color: theme.surface4
                                border.color: theme.border
                                border.width: 1
                                implicitHeight: narrativeContent.implicitHeight + 28

                                ColumnLayout {
                                    id: narrativeContent
                                    anchors.fill: parent
                                    anchors.margins: 14
                                    spacing: 8

                                    Label {
                                        text: sessionHeadline()
                                        color: theme.text
                                        font.pixelSize: root.denseLayout ? 20 : 24
                                        font.bold: true
                                        wrapMode: Text.Wrap
                                        Layout.fillWidth: true
                                    }
                                    Label {
                                        text: sessionNarrative()
                                        color: theme.muted
                                        wrapMode: Text.Wrap
                                        Layout.fillWidth: true
                                    }
                                    Flow {
                                        Layout.fillWidth: true
                                        spacing: 8
                                        InfoPill { textValue: backend.runtimeState.runtimeDisplayText || backend.runtimeState.statusLabel || backend.runtimeState.activeText || backend.tr("status_idle"); pillTone: statusTone() }
                                        InfoPill { textValue: backend.runtimeState.flow || "idle"; pillTone: "details" }
                                    }
                                }
                            }

                            GridLayout {
                                Layout.fillWidth: true
                                columns: width >= 420 ? 2 : 1
                                columnSpacing: 12
                                rowSpacing: 12

                                Repeater {
                                    model: [
                                        { title: trx("Decision", "Decision"), value: backend.runtimeState.trustLabel || backend.runtimeState.decisionLabel || backend.runtimeState.decisionText || backend.tr("status_idle"), tone: decisionTone() },
                                        { title: trx("Risk", "Risk"), value: backend.runtimeState.riskText || "--", tone: "warn" },
                                        { title: trx("Average risk", "Average risk"), value: backend.runtimeState.avgRiskText || "--", tone: "info" },
                                        { title: trx("Elapsed", "Elapsed"), value: backend.runtimeState.elapsed || "--", tone: "details" }
                                    ]

                                    delegate: Rectangle {
                                        Layout.fillWidth: true
                                        radius: 16
                                        color: theme.surface1
                                        border.color: theme.border
                                        border.width: 1
                                        implicitHeight: signalColumn.implicitHeight + 24

                                        ColumnLayout {
                                            id: signalColumn
                                            anchors.fill: parent
                                            anchors.margins: 12
                                            spacing: 8
                                            Label { text: modelData.title; color: theme.muted; font.bold: true; Layout.fillWidth: true; wrapMode: Text.Wrap }
                                            InfoPill { textValue: modelData.value; pillTone: modelData.tone }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    GlassCard {
                        Layout.fillWidth: true
                        implicitHeight: telemetryColumn.implicitHeight + 40

                        ColumnLayout {
                            id: telemetryColumn
                            anchors.fill: parent
                            anchors.margins: root.denseLayout ? 18 : 24
                            spacing: 12

                            SectionHeader {
                                title: trx("Live telemetry", "Live telemetry")
                                subtitle: trx("قراءات المراقب الحالية للجلسة المحمية.", "Current monitor telemetry for the protected session.")
                            }

                            Repeater {
                                model: telemetryListModel

                                delegate: Rectangle {
                                    Layout.fillWidth: true
                                    radius: 16
                                    color: theme.surface2
                                    border.color: theme.border
                                    implicitHeight: rowContent.implicitHeight + 28

                                    ColumnLayout {
                                        id: rowContent
                                        anchors.fill: parent
                                        anchors.margins: 14
                                        spacing: 8

                                        Label {
                                            text: modelData.label
                                            color: theme.muted
                                            font.bold: true
                                            Layout.fillWidth: true
                                            wrapMode: Text.Wrap
                                        }
                                        InfoPill {
                                            textValue: modelData.value
                                            pillTone: modelData.tone
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                GlassCard {
                    Layout.fillWidth: true
                    implicitHeight: guideColumn.implicitHeight + 44

                    ColumnLayout {
                        id: guideColumn
                        anchors.fill: parent
                        anchors.margins: 22
                        spacing: 14

                        SectionHeader {
                            title: trx("Response guide", "Response guide")
                            subtitle: trx("مساحة توضيحية بدل تكرار العدّاد الدائري أو شريط الأوامر القديم.", "An explanatory area instead of repeating the circular trust gauge or the old control rail.")
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: root.compactLayout ? 1 : 3
                            columnSpacing: 12
                            rowSpacing: 12

                            Rectangle {
                                Layout.fillWidth: true
                                radius: 18
                                color: theme.surface1
                                border.color: theme.border
                                border.width: 1
                                implicitHeight: readinessColumn.implicitHeight + 24
                                ColumnLayout {
                                    id: readinessColumn
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 8
                                    Label { text: trx("Readiness", "Readiness"); color: theme.muted; font.bold: true }
                                    InfoPill { textValue: backend.profile.ready ? trx("Profile ready", "Profile ready") : trx("Baseline still learning", "Baseline still learning"); pillTone: backend.profile.ready ? "success" : "warn" }
                                    Label { text: backend.profile.progressText || nextStepText(); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                radius: 18
                                color: theme.surface1
                                border.color: theme.border
                                border.width: 1
                                implicitHeight: diagnosticsColumn.implicitHeight + 24
                                ColumnLayout {
                                    id: diagnosticsColumn
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 8
                                    Label { text: trx("Diagnostics focus", "Diagnostics focus"); color: theme.muted; font.bold: true }
                                    InfoPill { textValue: backend.runtimeState.technicalFailure ? trx("Attention needed", "Attention needed") : trx("No hard failure", "No hard failure"); pillTone: backend.runtimeState.technicalFailure ? "danger" : "details" }
                                    Label { text: backend.runtimeState.lockSuppressionReasonText || backend.runtimeState.evidenceStallReasonText || backend.runtimeState.evidenceWaitingReasonText || backend.runtimeState.escalationPolicyText || backend.runtimeState.diagnosticText || trx("لا توجد رسالة تشخيصية موسعة الآن، ويتم الاكتفاء بالحالة الحية الحالية.", "There is no extended diagnostic note right now, so the live state is the main signal."); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                radius: 18
                                color: theme.surface1
                                border.color: theme.border
                                border.width: 1
                                implicitHeight: operatorColumn.implicitHeight + 24
                                ColumnLayout {
                                    id: operatorColumn
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 8
                                    Label { text: trx("Operator note", "Operator note"); color: theme.muted; font.bold: true }
                                    InfoPill { textValue: backend.runtimeState.active ? trx("Observe only", "Observe only") : trx("Ready when you are", "Ready when you are"); pillTone: backend.runtimeState.active ? "info" : "neutral" }
                                    Label { text: nextStepText(); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
