import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Dialog {
    id: root
    signal newUserSlidesFinished(bool skipped)
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property bool tourMode: backend.onboardingMode === "tour"
    property bool performanceMode: backend.onboardingMode === "performance"
    property int slideCount: backend.onboardingSlides ? backend.onboardingSlides.length : 0
    property int lastSlideIndex: Math.max(0, slideCount - 1)
    property int tourCurrentIndex: 0
    property bool onboardingDoNotShowAgain: false
    property var tourViewRef: null
    property var policyCheckRef: null
    property var planCheckRef: null
    property color readableText: theme.text
    property color readableSubtext: Qt.rgba(1, 1, 1, 0.82)
    modal: true
    closePolicy: Popup.NoAutoClose
    anchors.centerIn: Overlay.overlay
    width: root.tourMode ? rootWindow.width : Math.min(rootWindow.width - 40, rootWindow.denseWidth ? 760 : 920)
    height: root.tourMode ? rootWindow.height : Math.min(rootWindow.height - 36, rootWindow.shortHeight ? 680 : 780)
    padding: 0
    background: GlassCard {
        visible: !root.tourMode
        theme: root.theme
    }
    Overlay.modal: Rectangle {
        color: root.tourMode ? Qt.rgba(0.0, 0.04, 0.10, 0.42) : (theme.isDark ? "#b308101c" : "#8a0d1626")
    }

    function trx(arText, enText) { return rootWindow ? rootWindow.trx(arText, enText) : enText }
    function modeTitle(mode) {
        if (mode === "classic") return trx("خفيف", "Light")
        if (mode === "hybrid") return trx("حماية محسّنة", "Enhanced protection")
        if (mode === "hybrid_accelerated") return trx("حماية محسّنة أسرع", "Faster enhanced")
        return trx("ذكي (موصى به)", "Smart (recommended)")
    }
    function modeDescription(mode) {
        if (mode === "classic") return trx("يحافظ على أقل حمل ممكن على الجهاز ويستخدم المحرك الأساسي فقط.", "Keeps device load low and uses the core engine only.")
        if (mode === "hybrid") return trx("يضيف تحليلًا سلوكيًا أعمق لرفع الدقة عندما يكون الجهاز قادرًا على ذلك.", "Adds deeper behavior analysis for stronger accuracy when the device can handle it.")
        if (mode === "hybrid_accelerated") return trx("يشغّل الحماية المحسّنة عبر مسار أسرع عند توفره، وإلا يعود تلقائيًا للمسار الآمن.", "Runs enhanced protection through a faster path when available, otherwise it safely falls back.")
        return trx("يترك BioAuth يختار تلقائيًا الوضع الأنسب بناءً على فحص الجهاز.", "Lets BioAuth choose the safest suitable mode automatically after a device check.")
    }
    function modeHelp(mode) {
        if (mode === "classic") return trx("استخدم هذا إذا أردت أقل استهلاك ممكن للمعالج والذاكرة.", "Use this if you want the lowest CPU and memory usage.")
        if (mode === "hybrid") return trx("مفيد عندما تريد طبقة تحليل إضافية، لكنه قد يستهلك موارد أكثر قليلًا.", "Helpful when you want an extra analysis layer, but it can use a bit more resources.")
        if (mode === "hybrid_accelerated") return trx("مناسب إذا كان جهازك يدعم المسار الأسرع. إذا لم يكن متاحًا فلن يتعطل التطبيق وسيعود تلقائيًا إلى الوضع الآمن.", "Best when your device supports the faster path. If it is unavailable, the app safely falls back automatically.")
        return trx("الخيار الأنسب لمعظم الحالات لأنه يوازن بين الأداء والحماية.", "Best for most cases because it balances performance and protection.")
    }

    function toneColor(tone) {
        if (tone === "success") return theme.success
        if (tone === "warn") return theme.warn
        if (tone === "danger") return theme.danger
        if (tone === "details") return "#06b6d4"
        if (tone === "primary") return theme.primary
        return theme.info
    }

    function resetTourState() {
        tourCurrentIndex = 0
        onboardingDoNotShowAgain = false
        if (tourViewRef)
            tourViewRef.currentIndex = 0
    }

    header: Item {
        visible: !root.tourMode
        implicitHeight: root.tourMode ? 0 : 120
        RowLayout {
            anchors.fill: parent
            anchors.margins: 22
            spacing: 12

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6
                Label {
                    text: root.tourMode ? backend.tr("onboarding_title") : (root.performanceMode ? trx("اختر إعداد الأداء المناسب", "Choose your performance setup") : backend.onboardingTitle)
                    color: theme.text
                    font.pixelSize: rootWindow.denseWidth ? 24 : 28
                    font.bold: true
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
                Label {
                    text: root.tourMode ? backend.tr("onboarding_subtitle") : (root.performanceMode ? trx("هذه خطوة نهائية بسيطة تساعد BioAuth على اختيار المحرك الأنسب لجهازك من البداية.", "This final step helps BioAuth start with the engine that best fits your device.") : backend.onboardingSubtitle)
                    color: root.readableSubtext
                    wrapMode: Text.Wrap
                    Layout.fillWidth: true
                }
            }

            AppButton {
                visible: root.tourMode
                text: backend.tr("onboarding_skip")
                role: "neutral"
                compact: true
                onClicked: {
                    root.newUserSlidesFinished(true)
                    backend.skipNewUserOnboarding()
                }
            }
        }
    }

    contentItem: Loader {
        active: true
        sourceComponent: root.tourMode ? tourComponent : (root.performanceMode ? performanceComponent : consentComponent)
    }

    footer: Loader {
        active: !root.tourMode
        sourceComponent: root.performanceMode ? performanceFooterComponent : consentFooterComponent
    }

    Component {
        id: tourComponent
        Item {
            id: tourStage
            clip: true
            focus: true

            Component.onCompleted: {
                root.tourViewRef = tourView
                root.tourCurrentIndex = tourView.currentIndex
                tourStage.forceActiveFocus()
            }
            Component.onDestruction: {
                if (root.tourViewRef === tourView)
                    root.tourViewRef = null
            }

            Keys.onLeftPressed: {
                if (root.tourViewRef && root.tourCurrentIndex > 0)
                    root.tourViewRef.currentIndex = Math.max(0, root.tourViewRef.currentIndex - 1)
            }
            Keys.onRightPressed: {
                if (root.tourViewRef && root.tourCurrentIndex < root.lastSlideIndex)
                    root.tourViewRef.currentIndex = Math.min(root.lastSlideIndex, root.tourViewRef.currentIndex + 1)
            }

            SwipeView {
                id: tourView
                anchors.fill: parent
                clip: true
                currentIndex: root.tourCurrentIndex
                interactive: true
                onCurrentIndexChanged: root.tourCurrentIndex = currentIndex

                Repeater {
                    model: backend.onboardingSlides
                    delegate: Item {
                        required property var modelData

                        Image {
                            anchors.fill: parent
                            source: String(modelData.imageSource || "")
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            cache: true
                            smooth: true
                            mipmap: true
                        }

                        Rectangle {
                            anchors.fill: parent
                            color: "transparent"
                            gradient: Gradient {
                                GradientStop { position: 0.0; color: Qt.rgba(0.0, 0.04, 0.10, 0.12) }
                                GradientStop { position: 0.66; color: "transparent" }
                                GradientStop { position: 1.0; color: Qt.rgba(0.0, 0.02, 0.06, 0.18) }
                            }
                        }
                    }
                }
            }

            Rectangle {
                id: navigationPanel
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: Math.max(22, Math.round(parent.height * 0.048))
                width: Math.min(parent.width - 72, rootWindow.denseWidth ? 520 : 720)
                height: rootWindow.denseWidth ? 58 : 68
                radius: rootWindow.denseWidth ? 20 : 24
                color: Qt.rgba(0.0, 0.06, 0.14, 0.88)
                border.width: 1
                border.color: Qt.rgba(0.18, 0.72, 1.0, 0.34)

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 1
                    radius: parent.radius - 1
                    color: "transparent"
                    gradient: Gradient {
                        GradientStop { position: 0.0; color: Qt.rgba(1.0, 1.0, 1.0, 0.08) }
                        GradientStop { position: 1.0; color: "transparent" }
                    }
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: rootWindow.denseWidth ? 8 : 10
                    spacing: rootWindow.denseWidth ? 8 : 12

                    AppButton {
                        text: backend.tr("onboarding_back")
                        role: "neutral"
                        compact: rootWindow.denseWidth
                        enabled: root.tourCurrentIndex > 0
                        Layout.fillWidth: true
                        onClicked: {
                            if (root.tourViewRef)
                                root.tourViewRef.currentIndex = Math.max(0, root.tourViewRef.currentIndex - 1)
                        }
                    }

                    AppButton {
                        text: root.tourCurrentIndex >= root.lastSlideIndex ? root.trx("إنهاء", "Finish") : backend.tr("onboarding_next")
                        role: "primary"
                        compact: rootWindow.denseWidth
                        Layout.fillWidth: true
                        onClicked: {
                            if (root.tourCurrentIndex >= root.lastSlideIndex) {
                                root.newUserSlidesFinished(false)
                                backend.completeNewUserOnboarding(root.onboardingDoNotShowAgain)
                            } else if (root.tourViewRef) {
                                root.tourViewRef.currentIndex = Math.min(root.lastSlideIndex, root.tourViewRef.currentIndex + 1)
                            }
                        }
                    }
                }
            }
        }
    }

    Component {
        id: tourFooterComponent
        Item {
            implicitHeight: 92
            RowLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12

                AppButton {
                    text: backend.tr("onboarding_back")
                    role: "neutral"
                    enabled: root.tourCurrentIndex > 0
                    onClicked: {
                        if (root.tourViewRef)
                            root.tourViewRef.currentIndex = Math.max(0, root.tourViewRef.currentIndex - 1)
                    }
                }
                Item { Layout.fillWidth: true }
                PageIndicator {
                    count: root.slideCount
                    currentIndex: root.tourCurrentIndex
                    interactive: true
                    onCurrentIndexChanged: {
                        if (root.tourViewRef && root.tourCurrentIndex !== currentIndex)
                            root.tourViewRef.currentIndex = currentIndex
                    }
                }
                Item { Layout.fillWidth: true }
                AppButton {
                    text: root.tourCurrentIndex >= root.lastSlideIndex ? root.trx("إنهاء", "Finish") : backend.tr("onboarding_next")
                    role: "primary"
                    onClicked: {
                        if (root.tourCurrentIndex >= root.lastSlideIndex) {
                            root.newUserSlidesFinished(false)
                            backend.completeNewUserOnboarding(root.onboardingDoNotShowAgain)
                        } else if (root.tourViewRef)
                            root.tourViewRef.currentIndex = Math.min(root.lastSlideIndex, root.tourViewRef.currentIndex + 1)
                    }
                }
            }
        }
    }


    Component {
        id: performanceComponent
        ScrollView {
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            ColumnLayout {
                width: root.availableWidth
                spacing: 16

                GlassCard {
                    Layout.fillWidth: true
                    implicitHeight: performanceIntro.implicitHeight + 40
                    ColumnLayout {
                        id: performanceIntro
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 10
                        Label { text: trx("اختر الطريقة التي تريد أن توازن بها BioAuth بين استهلاك الجهاز وعمق التحليل.", "Choose how BioAuth should balance device usage with deeper analysis."); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: backend.deepRuntimeBenchmark && backend.deepRuntimeBenchmark.status === "ok" ? (trx("آخر توصية: ", "Last recommendation: ") + root.modeTitle(backend.deepRuntimeRecommendedMode || "classic")) : trx("يمكنك تشغيل فحص سريع للجهاز الآن، أو اختيار وضع يناسبك يدويًا.", "You can run a quick device check now, or pick a mode manually."); color: root.readableSubtext; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }

                GlassCard {
                    Layout.fillWidth: true
                    implicitHeight: quickCheckContent.implicitHeight + 40
                    ColumnLayout {
                        id: quickCheckContent
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 12
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 12
                            SectionHeader {
                                Layout.fillWidth: true
                                title: trx("فحص سريع للجهاز", "Quick device check")
                                subtitle: trx("اختبار محلي قصير يساعد BioAuth على اقتراح أفضل وضع دون إرسال بياناتك لأي مكان.", "A short local check that helps BioAuth suggest the best mode without sending your data anywhere.")
                            }
                            ToolButton {
                                text: "?"
                                implicitWidth: 30
                                implicitHeight: 30
                                padding: 0
                                background: Rectangle { radius: width / 2; color: theme.surface2; border.color: theme.border; border.width: 1 }
                                contentItem: Label { text: parent.text; color: theme.text; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter; font.bold: true }
                                ToolTip.visible: hovered
                                ToolTip.text: trx("هذا الاختبار يفحص الأداء محليًا فقط ليقرر إن كان المحرك الأعمق مناسبًا لهذا الجهاز.", "This check measures local performance only to see if the deeper engine is suitable for this device.")
                            }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            AppButton { text: backend.deepRuntimeBenchmark && backend.deepRuntimeBenchmark.status === "ok" ? trx("إعادة الفحص", "Run again") : trx("تشغيل الفحص", "Run check"); role: "primary"; onClicked: backend.runDeepRuntimeBenchmark() }
                            AppButton { text: trx("استخدم التوصية الذكية", "Use smart setup"); role: "neutral"; enabled: backend.deepRuntimeBenchmark && backend.deepRuntimeBenchmark.status === "ok"; onClicked: backend.setDeepRuntimeMode("auto") }
                        }
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: rootWindow.denseWidth ? 1 : 2
                    columnSpacing: 12
                    rowSpacing: 12

                    SelectableInfoCard {
                        theme: root.theme
                        titleText: root.modeTitle("auto")
                        descriptionText: root.modeDescription("auto")
                        helpText: root.modeHelp("auto")
                        badgeText: trx("AUTO", "AUTO")
                        accentColor: theme.primary
                        selected: backend.deepRuntimeMode === "auto"
                        onChosen: backend.setDeepRuntimeMode("auto")
                    }
                    SelectableInfoCard {
                        theme: root.theme
                        titleText: root.modeTitle("classic")
                        descriptionText: root.modeDescription("classic")
                        helpText: root.modeHelp("classic")
                        badgeText: trx("LITE", "LITE")
                        accentColor: "#06b6d4"
                        selected: backend.deepRuntimeMode === "classic"
                        onChosen: backend.setDeepRuntimeMode("classic")
                    }
                    SelectableInfoCard {
                        theme: root.theme
                        titleText: root.modeTitle("hybrid")
                        descriptionText: root.modeDescription("hybrid")
                        helpText: root.modeHelp("hybrid")
                        badgeText: trx("PLUS", "PLUS")
                        accentColor: theme.accent
                        selected: backend.deepRuntimeMode === "hybrid"
                        onChosen: backend.setDeepRuntimeMode("hybrid")
                    }
                    SelectableInfoCard {
                        theme: root.theme
                        titleText: root.modeTitle("hybrid_accelerated")
                        descriptionText: root.modeDescription("hybrid_accelerated")
                        helpText: root.modeHelp("hybrid_accelerated")
                        badgeText: trx("FAST", "FAST")
                        accentColor: "#22c55e"
                        selected: backend.deepRuntimeMode === "hybrid_accelerated"
                        onChosen: backend.setDeepRuntimeMode("hybrid_accelerated")
                    }
                }

                GlassCard {
                    Layout.fillWidth: true
                    implicitHeight: performanceSummary.implicitHeight + 36
                    ColumnLayout {
                        id: performanceSummary
                        anchors.fill: parent
                        anchors.margins: 18
                        spacing: 8
                        Label { text: trx("الاختيار الحالي", "Current choice"); color: theme.muted; font.bold: true }
                        Label { text: root.modeTitle(backend.deepRuntimeMode || "auto"); color: theme.text; font.bold: true }
                        Label { text: root.modeDescription(backend.deepRuntimeMode || "auto"); color: root.readableSubtext; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
            }
        }
    }

    Component {
        id: performanceFooterComponent
        Item {
            implicitHeight: 90
            RowLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12
                Item { Layout.fillWidth: true }
                AppButton { text: trx("حفظ والمتابعة", "Save and continue"); role: "primary"; onClicked: backend.completePerformanceSetupOnboarding() }
            }
        }
    }

    Component {
        id: consentComponent
        ScrollView {
            Component.onCompleted: {
                root.policyCheckRef = policyCheck
                root.planCheckRef = planCheck
            }
            Component.onDestruction: {
                if (root.policyCheckRef === policyCheck)
                    root.policyCheckRef = null
                if (root.planCheckRef === planCheck)
                    root.planCheckRef = null
            }
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ColumnLayout {
                width: root.availableWidth
                spacing: 16
                Label { text: backend.profile.progressText || ""; color: theme.accent; font.bold: true }
                GlassCard {
                    Layout.fillWidth: true
                    implicitHeight: 176
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 10
                        Label { text: rootWindow.trx("كيف تبدأ بشكل صحيح", "How to start correctly"); color: theme.text; font.pixelSize: 22; font.bold: true }
                        Label { text: rootWindow.trx("سجّل جلسات التعريف تدريجيًا عبر عدة أيام ليبني النظام baseline واقعيًا.", "Record enrollment gradually across multiple days so the system builds a realistic baseline."); color: root.readableText; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: rootWindow.trx("ابدأ التدريب بعد 8 جلسات جيدة على الأقل، والنسخة الأولى تفضّل بين 8 و15 جلسة.", "Start training after at least 8 good sessions, with 8 to 15 sessions preferred for the first profile."); color: root.readableSubtext; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
                CheckBox {
                    id: policyCheck
                    text: backend.tr("privacy_ack")
                    Layout.fillWidth: true
                    contentItem: Text {
                        text: policyCheck.text
                        color: root.readableText
                        wrapMode: Text.Wrap
                        leftPadding: policyCheck.indicator.width + policyCheck.spacing
                        font: policyCheck.font
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                CheckBox {
                    id: planCheck
                    text: backend.tr("plan_ack")
                    Layout.fillWidth: true
                    contentItem: Text {
                        text: planCheck.text
                        color: root.readableText
                        wrapMode: Text.Wrap
                        leftPadding: planCheck.indicator.width + planCheck.spacing
                        font: planCheck.font
                        verticalAlignment: Text.AlignVCenter
                    }
                }
                AppButton { text: backend.tr("open_policy"); role: "details"; onClicked: backend.openPrivacyPolicy() }
            }
        }
    }

    Component {
        id: consentFooterComponent
        Item {
            implicitHeight: 90
            RowLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 12
                AppButton { text: backend.tr("save_continue"); role: "neutral"; onClicked: backend.saveOnboarding(root.policyCheckRef ? root.policyCheckRef.checked : false, root.planCheckRef ? root.planCheckRef.checked : false, false) }
                AppButton { text: backend.tr("save_and_start"); role: "primary"; onClicked: backend.saveOnboarding(root.policyCheckRef ? root.policyCheckRef.checked : false, root.planCheckRef ? root.planCheckRef.checked : false, true) }
                Item { Layout.fillWidth: true }
            }
        }
    }

    onVisibleChanged: {
        if (!visible)
            resetTourState()
    }
}
