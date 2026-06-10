import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

GlassCard {
    id: panel
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property bool compact: width < 980
    property var runtime: backend.runtimeState || ({})
    property var profileData: backend.profile || ({})
    property var driftCards: runtime.driftLiveCards || []

    function trx(arText, enText) { return rootWindow ? rootWindow.trx(arText, enText) : enText }
    function safeText(value, fallback) { return (value === undefined || value === null || String(value).length === 0) ? fallback : String(value) }
    function toneColor(tone) { return rootWindow ? rootWindow.toneColor(tone) : theme.info }
    function cardAt(index, fallbackTitle, fallbackKind) {
        if (driftCards && driftCards.length > index && driftCards[index])
            return driftCards[index]
        return {
            kind: fallbackKind,
            title: fallbackTitle,
            statusText: "Unavailable",
            statusTone: "neutral",
            confidenceAvailable: false,
            confidenceText: "Backend runtimeState has not published this drift card yet.",
            trend: [],
            trendSource: "unavailable",
            trendUnavailableText: "Trend appears only when backend publishes real samples.",
            todayText: "No backend drift evidence is available yet.",
            baselineText: "Waiting for backend profile readiness before baseline interpretation.",
            explainabilityText: "No monitor explanation has been published yet.",
            whyText: "This card is waiting for runtimeState.driftLiveCards."
        }
    }
    function panelTone() {
        if (!profileData.ready)
            return "warn"
        if (runtime.technicalFailure)
            return "danger"
        if (runtime.awaitingEvidence)
            return "warn"
        if (runtime.active)
            return "success"
        return "neutral"
    }
    function panelStatus() {
        if (!profileData.ready)
            return trx("Waiting for baseline", "Waiting for baseline")
        if (runtime.technicalFailure)
            return trx("Unavailable", "Unavailable")
        if (runtime.lockSuppressionActive)
            return trx("Lock delayed", "Lock delayed")
        if (runtime.awaitingEvidence)
            return runtime.runtimeDisplayText || trx("Capturing live session", "Capturing live session")
        if (runtime.active)
            return trx("Live", "Live")
        return trx("Preview only", "Preview only")
    }
    function panelNarrative() {
        if (!profileData.ready)
            return trx("Drift Lab ينتظر baseline موثوق قبل تفسير إشارات keyboard وmouse وcombined.", "Drift Lab waits for a trusted baseline before interpreting keyboard, mouse, and combined signals.")
        if (runtime.lockSuppressionActive)
            return runtime.lockSuppressionReasonText || runtime.escalationPolicyText || trx("Drift Lab يعرض سبب تأخير القفل كما نشره backend فقط.", "Drift Lab shows the backend-published reason why locking is delayed.")
        if (runtime.evidenceWaitingReasonText)
            return runtime.evidenceWaitingReasonText
        if (runtime.active)
            return trx("البطاقات الحية تقرأ runtimeState الحالي فقط: capture counters، monitor windows، وrecent risks عند توفرها.", "Live cards read only current runtimeState: capture counters, monitor windows, and recent risks when available.")
        return trx("لا توجد جلسة محمية الآن؛ تظهر البطاقات حالة preview صادقة بدون نسب أو trends وهمية.", "No protected session is running; cards show an honest preview state without fake percentages or trends.")
    }

    implicitHeight: content.implicitHeight + 40

    ColumnLayout {
        id: content
        anchors.fill: parent
        anchors.margins: 22
        spacing: 16

        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 5
                Label {
                    text: trx("Live Drift Lab", "Live Drift Lab")
                    color: theme.text
                    font.pixelSize: 24
                    font.bold: true
                    Layout.fillWidth: true
                }
                Label {
                    text: panelNarrative()
                    color: theme.muted
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
            }
            Rectangle {
                radius: 999
                color: toneColor(panelTone())
                implicitWidth: panelBadge.implicitWidth + 24
                implicitHeight: 34
                Label { id: panelBadge; anchors.centerIn: parent; text: panelStatus(); color: theme.chipText || "white"; font.bold: true; font.pixelSize: 12 }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: panel.compact ? 1 : 3
            columnSpacing: 12
            rowSpacing: 12

            Repeater {
                model: [
                    cardAt(0, trx("Keyboard drift", "Keyboard drift"), "keyboard"),
                    cardAt(1, trx("Mouse drift", "Mouse drift"), "mouse"),
                    cardAt(2, trx("Combined drift", "Combined drift"), "combined")
                ]
                delegate: DriftSignalCard {
                    rootWindow: panel.rootWindow
                    cardData: modelData
                    baselineReady: !!profileData.ready
                    Layout.fillWidth: true
                }
            }
        }
    }
}
