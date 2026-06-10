import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme

    readonly property var profileData: backend.profile || ({})
    readonly property var runtimeData: backend.runtimeState || ({})
    readonly property var shadowData: backend.shadowStatus || ({})
    readonly property bool baselineReady: !!profileData.ready
    readonly property bool runtimeActive: !!runtimeData.active

    function trx(arText, enText) { return rootWindow ? rootWindow.trx(arText, enText) : enText }
    function safeText(value, fallback) {
        if (value === undefined || value === null)
            return fallback
        var text = String(value)
        return text.length > 0 ? text : fallback
    }
    function safeInt(value, fallback) {
        if (value === undefined || value === null || value === "")
            return fallback
        var parsed = Number(value)
        return isNaN(parsed) ? fallback : Math.round(parsed)
    }
    function safeNumber(value, fallback) {
        if (value === undefined || value === null || value === "")
            return fallback
        var parsed = Number(value)
        return isNaN(parsed) ? fallback : parsed
    }
    function phaseTone() {
        var phase = safeText(shadowData.phase, "collecting").toLowerCase()
        if (shadowData.promote_suggested)
            return "success"
        if (phase === "evaluating")
            return "info"
        if (phase === "training_pending")
            return "warn"
        return "neutral"
    }
    function phaseText() {
        var phase = safeText(shadowData.phase, "collecting").toLowerCase()
        if (phase === "training_pending")
            return trx("تجهيز تدريب shadow", "Preparing shadow training")
        if (phase === "evaluating")
            return trx("مقارنة صامتة", "Silent evaluation")
        if (phase === "ready")
            return trx("جاهز للترقية", "Ready for promotion")
        return trx("جمع عينات موثوقة", "Collecting trusted samples")
    }
    function labNarrative() {
        if (!baselineReady)
            return trx("تبدأ بطاقات Drift Lab بحالة انتظار صادقة إلى أن يتوفر baseline موثوق، ثم تعرض إشارات runtime الحقيقية فقط.", "Drift Lab cards start in an honest waiting state until a trusted baseline exists, then show only real runtime signals.")
        return trx("تعرض الصفحة الآن بطاقات keyboard وmouse وcombined مبنية على runtimeState الحقيقي، مع trend فقط عندما ينشر monitor عينات risk حديثة.", "The page now shows keyboard, mouse, and combined cards built from real runtimeState, with a trend only when the monitor publishes recent risk samples.")
    }
    function runtimeNarrative() {
        if (!runtimeActive)
            return trx("لا توجد جلسة محمية تعمل الآن، لذلك أي قراءة هنا هي مجرد وضع standby حقيقي وليست analytics افتراضية.", "There is no protected session running right now, so the state shown here is a true standby mode rather than fabricated analytics.")
        return trx("قرار الجلسة: ", "Session decision: ") + safeText(runtimeData.trustLabel, safeText(runtimeData.decisionLabel, safeText(runtimeData.decisionText, backend.tr("status_idle"))))
             + trx(" • المخاطرة: ", " • Risk: ") + safeText(runtimeData.riskText, "--")
             + trx(" • المتوسط: ", " • Avg risk: ") + safeText(runtimeData.avgRiskText, "--")
             + trx(" • الزمن: ", " • Elapsed: ") + safeText(runtimeData.elapsed, "--")
             + (runtimeData.lockSuppressionReasonText ? (trx(" • السبب: ", " • Why: ") + runtimeData.lockSuppressionReasonText) : (runtimeData.evidenceWaitingReasonText ? (trx(" • السبب: ", " • Why: ") + runtimeData.evidenceWaitingReasonText) : ""))
    }
    function shadowNarrative() {
        var avgDelta = safeNumber(shadowData.pending_avg_delta, safeNumber(shadowData.avg_delta, 0))
        return trx("المرحلة: ", "Phase: ") + safeText(shadowData.phase, "collecting")
             + trx(" • الجلسات الموثوقة: ", " • Trusted sessions: ") + String(safeInt(shadowData.candidate_count, 0))
             + trx(" • التقييمات: ", " • Evaluations: ") + String(safeInt(shadowData.eval_count, 0))
             + trx(" • متوسط الفرق: ", " • Avg delta: ") + avgDelta.toFixed(1)
    }

    ScrollView {
        anchors.fill: parent
        clip: true

        Item {
            width: parent.width
            implicitHeight: contentColumn.implicitHeight + 16

            ColumnLayout {
                id: contentColumn
                width: parent.width
                spacing: 16

                DriftLabPanel {
                    rootWindow: root.rootWindow
                    Layout.fillWidth: true
                }

                GlassCard {
                    Layout.fillWidth: true
                    implicitHeight: heroColumn.implicitHeight + 40
                    ColumnLayout {
                        id: heroColumn
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 12

                        SectionHeader {
                            Layout.fillWidth: true
                            title: trx("Drift Lab — live evidence cards", "Drift Lab — live evidence cards")
                            subtitle: trx("Keyboard وmouse وcombined تظهر من runtimeState الحقيقي فقط، ولا تعرض trend أو confidence إذا لم ينشرها الـ backend.", "Keyboard, mouse, and combined cards come only from real runtimeState, and do not show trend or confidence unless the backend publishes evidence.")
                        }

                        Flow {
                            Layout.fillWidth: true
                            spacing: 10
                            InfoPill { textValue: baselineReady ? trx("Baseline ready", "Baseline ready") : trx("Baseline building", "Baseline building"); pillTone: baselineReady ? "success" : "warn" }
                            InfoPill { textValue: runtimeActive ? trx("Live session visible", "Live session visible") : trx("No live session", "No live session"); pillTone: runtimeActive ? "info" : "neutral" }
                            InfoPill { textValue: phaseText(); pillTone: phaseTone() }
                        }

                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            color: theme.text
                            text: labNarrative()
                        }
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: width >= 1180 ? 3 : (width >= 760 ? 2 : 1)
                    columnSpacing: 16
                    rowSpacing: 16

                    StatTile {
                        Layout.fillWidth: true
                        title: trx("Baseline", "Baseline")
                        value: baselineReady ? trx("Ready", "Ready") : trx("Learning", "Learning")
                        subtitle: profileData.progressText || trx("Baseline readiness driven by trusted enrollment sessions.", "Baseline readiness driven by trusted enrollment sessions.")
                        accentColor: baselineReady ? theme.success : theme.warn
                        badge: trx("Sessions", "Sessions") + ": " + String(safeInt(profileData.session_count, 0))
                    }
                    StatTile {
                        Layout.fillWidth: true
                        title: trx("Runtime", "Runtime")
                        value: safeText(runtimeData.statusLabel, safeText(runtimeData.activeText, backend.tr("status_idle")))
                        subtitle: runtimeNarrative()
                        accentColor: runtimeActive ? theme.info : theme.primary
                        badge: safeText(runtimeData.flow, "idle")
                    }
                    StatTile {
                        Layout.fillWidth: true
                        title: trx("Shadow lifecycle", "Shadow lifecycle")
                        value: phaseText()
                        subtitle: shadowNarrative()
                        accentColor: phaseTone() === "success" ? theme.success : (phaseTone() === "warn" ? theme.warn : theme.info)
                        badge: safeText(shadowData.phase, "collecting")
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: width >= 1120 ? 2 : 1
                    columnSpacing: 16
                    rowSpacing: 16

                    GlassCard {
                        Layout.fillWidth: true
                        implicitHeight: observationColumn.implicitHeight + 40
                        ColumnLayout {
                            id: observationColumn
                            anchors.fill: parent
                            anchors.margins: 20
                            spacing: 12

                            SectionHeader {
                                title: trx("Observation map", "Observation map")
                                subtitle: trx("ثلاث طبقات واضحة: baseline، runtime، ثم shadow evaluation.", "Three clear layers: baseline, runtime, then shadow evaluation.")
                            }

                            Repeater {
                                model: [
                                    { title: trx("Baseline layer", "Baseline layer"), pill: baselineReady ? trx("Stable", "Stable") : trx("Still collecting", "Still collecting"), tone: baselineReady ? "success" : "warn", body: profileData.progressText || trx("يتم استخدام جلسات التهيئة الموثوقة فقط لبناء المرجع الأساسي.", "Only trusted enrollment sessions are used to build the reference baseline.") },
                                    { title: trx("Runtime layer", "Runtime layer"), pill: safeText(runtimeData.decisionText, backend.tr("status_idle")), tone: runtimeActive ? "info" : "neutral", body: runtimeNarrative() },
                                    { title: trx("Shadow layer", "Shadow layer"), pill: phaseText(), tone: phaseTone(), body: shadowNarrative() }
                                ]
                                delegate: Rectangle {
                                    Layout.fillWidth: true
                                    radius: 18
                                    color: theme.surface4
                                    border.color: theme.border
                                    border.width: 1
                                    implicitHeight: layerColumn.implicitHeight + 24
                                    ColumnLayout {
                                        id: layerColumn
                                        anchors.fill: parent
                                        anchors.margins: 12
                                        spacing: 8
                                        RowLayout {
                                            Layout.fillWidth: true
                                            Label { text: modelData.title; color: theme.text; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                            InfoPill { textValue: modelData.pill; pillTone: modelData.tone }
                                        }
                                        Label { text: modelData.body; color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    }
                                }
                            }
                        }
                    }

                    GlassCard {
                        Layout.fillWidth: true
                        implicitHeight: interpretationColumn.implicitHeight + 40
                        ColumnLayout {
                            id: interpretationColumn
                            anchors.fill: parent
                            anchors.margins: 20
                            spacing: 12

                            SectionHeader {
                                title: trx("Interpretation guide", "Interpretation guide")
                                subtitle: trx("ما الذي تقرأه هنا وما الذي لا تدّعيه الصفحة عمدًا.", "What this page is telling you and what it intentionally avoids claiming.")
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                radius: 18
                                color: theme.surface1
                                border.color: theme.border
                                border.width: 1
                                implicitHeight: notesColumn.implicitHeight + 24
                                ColumnLayout {
                                    id: notesColumn
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 8
                                    Label { text: trx("What is real", "What is real"); color: theme.text; font.bold: true }
                                    Label { text: trx(["• جاهزية baseline", "• حالة الجلسة الحية الحالية", "• دورة حياة نموذج الظل واقتراحات الترقية"].join("\n"), ["• Baseline readiness", "• The current live-session state", "• Shadow-model lifecycle and promotion suggestions"].join("\n")); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                    Label { text: trx("What is intentionally omitted", "What is intentionally omitted"); color: theme.text; font.bold: true }
                                    Label { text: trx(["• نسب drift وهمية", "• دلتا keyboard/mouse غير صادرة من الـ backend", "• رسوم trend مزخرفة بلا مصدر حقيقي"].join("\n"), ["• Fake drift percentages", "• Keyboard/mouse deltas not emitted by the backend", "• Decorative trend charts without a real source"].join("\n")); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                }
                            }

                            Rectangle {
                                Layout.fillWidth: true
                                radius: 18
                                color: theme.surface4
                                border.color: theme.border
                                border.width: 1
                                implicitHeight: opportunityColumn.implicitHeight + 24
                                ColumnLayout {
                                    id: opportunityColumn
                                    anchors.fill: parent
                                    anchors.margins: 12
                                    spacing: 8
                                    Label { text: trx("Next opportunities", "Next opportunities"); color: theme.text; font.bold: true }
                                    Label { text: !baselineReady ? trx("أكمل جلسات التهيئة لفتح صورة أوضح داخل المختبر.", "Complete enrollment sessions to unlock a clearer picture inside the lab.") : (runtimeActive ? trx("راقب الاختلاف بين الحالة الحية وshadow lifecycle بدل البحث عن رسوم متخيلة.", "Watch the relationship between the live state and the shadow lifecycle instead of looking for imaginary charts.") : trx("شغّل جلسة محمية لاحقًا لترى طبقة runtime وهي تتحدث هنا مباشرة.", "Start a protected session later to see the runtime layer speak here directly.")); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                                }
                            }
                        }
                    }
                }

                GlassCard {
                    Layout.fillWidth: true
                    implicitHeight: actionColumn.implicitHeight + 40
                    ColumnLayout {
                        id: actionColumn
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 12
                        SectionHeader {
                            title: trx("Safe actions", "Safe actions")
                            subtitle: trx("الأزرار هنا خفيفة وتستدعي نفس مسارات التطبيق الأصلية بدون أي حلقات تحديث إضافية.", "The actions here are light and call the same native app flows without extra refresh loops.")
                        }
                        Flow {
                            Layout.fillWidth: true
                            spacing: 12
                            AppButton { text: trx("بدء جلسة محمية", "Start protected"); role: "primary"; compact: true; enabled: backend.canStartProtected; onClicked: backend.startProtected() }
                            AppButton { text: trx("تدريب الملف", "Train profile"); role: "success"; compact: true; enabled: backend.canTrain; onClicked: backend.trainProfile() }
                        }
                    }
                }
            }
        }
    }
}
