import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: card
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property var cardData: ({})
    property bool baselineReady: true
    property bool compact: width < 360

    function trx(arText, enText) { return rootWindow ? rootWindow.trx(arText, enText) : enText }
    function safeText(value, fallback) {
        if (value === undefined || value === null)
            return fallback
        var text = String(value)
        return text.length > 0 ? text : fallback
    }
    function toneColor(tone) { return rootWindow ? rootWindow.toneColor(tone) : theme.info }
    function fallbackTone() {
        return baselineReady ? safeText(cardData.statusTone, "neutral") : "warn"
    }
    function statusText() {
        if (!baselineReady)
            return trx("Waiting for baseline", "Waiting for baseline")
        return safeText(cardData.statusText, trx("Unavailable", "Unavailable"))
    }
    function numericTrend() {
        var source = cardData.trend || []
        var points = []
        for (var i = 0; i < source.length; ++i) {
            var n = Number(source[i])
            if (!isNaN(n))
                points.push(n)
        }
        return points
    }
    function hasTrend() { return numericTrend().length >= 2 }
    function confidenceText() {
        if (cardData.confidenceAvailable)
            return safeText(cardData.confidenceText, trx("Evidence available", "Evidence available"))
        return safeText(cardData.confidenceText, trx("Not enough backend evidence yet", "Not enough backend evidence yet"))
    }
    function baselineText() {
        if (!baselineReady)
            return trx("Waiting for trusted baseline from backend profile readiness.", "Waiting for trusted baseline from backend profile readiness.")
        return safeText(cardData.baselineText, trx("Trusted baseline is available; this card still waits for backend drift diagnostics before making stronger claims.", "Trusted baseline is available; this card still waits for backend drift diagnostics before making stronger claims."))
    }

    Layout.fillWidth: true
    radius: 20
    color: theme.surface4
    border.color: toneColor(fallbackTone())
    border.width: 1
    implicitHeight: signalContent.implicitHeight + 28

    ColumnLayout {
        id: signalContent
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Label {
                text: safeText(cardData.title, trx("Drift signal", "Drift signal"))
                color: theme.text
                font.pixelSize: 18
                font.bold: true
                Layout.fillWidth: true
                wrapMode: Text.Wrap
            }
            Rectangle {
                radius: 999
                color: toneColor(fallbackTone())
                implicitWidth: statusLabel.implicitWidth + 20
                implicitHeight: 30
                Label {
                    id: statusLabel
                    anchors.centerIn: parent
                    text: statusText()
                    color: theme.chipText || "white"
                    font.bold: true
                    font.pixelSize: 11
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: card.compact ? 1 : 3
            columnSpacing: 12
            rowSpacing: 8

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Label { text: trx("Today", "Today"); color: theme.muted; font.pixelSize: 11; font.bold: true }
                Label {
                    Layout.fillWidth: true
                    text: baselineReady ? safeText(cardData.todayText, trx("No live evidence available yet.", "No live evidence available yet.")) : trx("Complete a trusted baseline before live drift interpretation.", "Complete a trusted baseline before live drift interpretation.")
                    color: theme.text
                    wrapMode: Text.Wrap
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Label { text: trx("Baseline", "Baseline"); color: theme.muted; font.pixelSize: 11; font.bold: true }
                Label {
                    Layout.fillWidth: true
                    text: baselineText()
                    color: baselineReady ? theme.text : theme.muted
                    wrapMode: Text.Wrap
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                Label { text: trx("Confidence", "Confidence"); color: theme.muted; font.pixelSize: 11; font.bold: true }
                Label {
                    Layout.fillWidth: true
                    text: confidenceText()
                    color: cardData.confidenceAvailable ? theme.text : theme.muted
                    wrapMode: Text.Wrap
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            radius: 16
            color: theme.surface1
            border.color: theme.border
            border.width: 1
            implicitHeight: trendColumn.implicitHeight + 18
            ColumnLayout {
                id: trendColumn
                anchors.fill: parent
                anchors.margins: 9
                spacing: 7
                RowLayout {
                    Layout.fillWidth: true
                    Label { text: trx("7-session trend", "7-session trend"); color: theme.text; font.bold: true; Layout.fillWidth: true }
                    Label { text: safeText(cardData.trendSource, ""); color: theme.muted; font.pixelSize: 10; visible: hasTrend() }
                }
                MiniTrendChart {
                    Layout.fillWidth: true
                    implicitHeight: 70
                    visible: hasTrend()
                    dataPoints: card.numericTrend()
                    theme: card.theme
                    strokeColor: toneColor(fallbackTone())
                }
                Label {
                    Layout.fillWidth: true
                    visible: !hasTrend()
                    text: safeText(cardData.trendUnavailableText, trx("Trend appears only when backend publishes enough real samples.", "Trend appears only when backend publishes enough real samples."))
                    color: theme.muted
                    wrapMode: Text.Wrap
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4
            Label { text: trx("Explainability", "Explainability"); color: theme.muted; font.pixelSize: 11; font.bold: true }
            Label {
                Layout.fillWidth: true
                text: safeText(cardData.explainabilityText, trx("No monitor explanation has been published yet.", "No monitor explanation has been published yet."))
                color: theme.text
                wrapMode: Text.Wrap
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 4
            Label { text: trx("Why this result", "Why this result"); color: theme.muted; font.pixelSize: 11; font.bold: true }
            Label {
                Layout.fillWidth: true
                text: safeText(cardData.whyText, trx("The card is waiting for backend runtime evidence.", "The card is waiting for backend runtime evidence."))
                color: theme.muted
                wrapMode: Text.Wrap
            }
        }
    }
}
