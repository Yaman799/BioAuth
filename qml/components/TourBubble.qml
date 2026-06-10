import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

GlassCard {
    id: root
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    property string titleText: ""
    property string bodyText: ""
    property string stepText: ""
    property bool canGoBack: false
    property bool isLastStep: false
    property bool isArabic: backend.language === "ar"

    signal backRequested()
    signal nextRequested()
    signal skipRequested()
    signal finishRequested()

    readonly property bool compactBubble: width < 360
    readonly property real contentMargin: compactBubble ? 14 : 20
    readonly property int titleSize: compactBubble ? 18 : 21
    readonly property int bodySize: compactBubble ? 13 : 14

    implicitWidth: 420
    implicitHeight: bubbleLayout.implicitHeight + contentMargin * 2
    radius: compactBubble ? 22 : 26

    LayoutMirroring.enabled: root.isArabic
    LayoutMirroring.childrenInherit: true

    ColumnLayout {
        id: bubbleLayout
        anchors.fill: parent
        anchors.margins: root.contentMargin
        spacing: root.compactBubble ? 10 : 14

        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            InfoPill {
                theme: root.theme
                textValue: root.stepText
                pillTone: "info"
                visible: root.stepText.length > 0
            }

            Item {
                Layout.fillWidth: true
            }

            AppButton {
                id: skipButton
                theme: root.theme
                text: root.isArabic ? "تخطي" : "Skip"
                role: "neutral"
                compact: true
                onClicked: root.skipRequested()
            }
        }

        Label {
            id: titleLabel
            Layout.fillWidth: true
            text: root.titleText
            color: root.theme.text
            font.pixelSize: root.titleSize
            font.bold: true
            wrapMode: Text.WordWrap
            maximumLineCount: root.compactBubble ? 4 : 3
            elide: Text.ElideRight
            horizontalAlignment: root.isArabic ? Text.AlignRight : Text.AlignLeft
        }

        Label {
            id: bodyLabel
            Layout.fillWidth: true
            text: root.bodyText
            color: root.theme.muted
            font.pixelSize: root.bodySize
            lineHeight: root.compactBubble ? 1.12 : 1.16
            wrapMode: Text.WordWrap
            maximumLineCount: root.compactBubble ? 7 : 6
            elide: Text.ElideRight
            horizontalAlignment: root.isArabic ? Text.AlignRight : Text.AlignLeft
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: root.compactBubble ? 8 : 10

            AppButton {
                id: backButton
                theme: root.theme
                text: root.isArabic ? "السابق" : "Back"
                role: "neutral"
                compact: true
                enabled: root.canGoBack
                onClicked: root.backRequested()
            }

            Item {
                Layout.fillWidth: true
            }

            AppButton {
                id: nextButton
                theme: root.theme
                text: root.isArabic ? "التالي" : "Next"
                role: "primary"
                compact: true
                visible: !root.isLastStep
                onClicked: root.nextRequested()
            }

            AppButton {
                id: finishButton
                theme: root.theme
                text: root.isArabic ? "إنهاء" : "Finish"
                role: "primary"
                compact: true
                visible: root.isLastStep
                onClicked: root.finishRequested()
            }
        }
    }
}
