import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"
import "../../theme/Ui.js" as Ui

ScrollView {
    id: root
    clip: true
    contentWidth: Math.max(0, availableWidth)
    contentHeight: activityContent.implicitHeight
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme

    readonly property bool isArabic: backend.language === "ar"
    readonly property bool compactLayout: width < 820
    readonly property var sessionList: backend.sessions || []
    readonly property var dashboardState: backend.dashboardState || ({})
    readonly property var runtimeState: backend.runtimeState || ({})
    readonly property var autoEnrollment: backend.autoEnrollmentState || ({})
    readonly property var modelReadiness: backend.modelReadinessState || ({})

    readonly property url activityIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/08_activity_history.png")
    readonly property url protectionIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/02_protection_shield.png")
    readonly property url sessionIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/10_session_monitor.png")
    readonly property url learningIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/17_model_brain.png")
    readonly property url infoIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/22_info.png")

    LayoutMirroring.enabled: root.isArabic
    LayoutMirroring.childrenInherit: true

    function label(arText, enText) {
        return Ui.trx(root.isArabic, arText, enText)
    }

    function tourTarget(name) {
        if (name === "activityHeader") return activityHeaderCard
        return null
    }

    function safeString(value, fallbackText) {
        var text = String(value === undefined || value === null ? "" : value)
        return text.length > 0 ? text : (fallbackText || "")
    }

    function requestFullHistory() {
        try {
            if (backend.loadFullHistory)
                backend.loadFullHistory()
        } catch (e) {}
    }

    function safeDecisionText(value) {
        var text = root.safeString(value, "—")
        var lower = text.toLowerCase()
        if (lower === "legit" || lower === "trusted" || lower === "accepted")
            return root.label("موثوقة", "Trusted")
        if (lower === "intruder" || lower === "suspicious" || lower === "blocked")
            return root.label("تحتاج مراجعة", "Needs attention")
        if (lower === "unknown" || lower === "pending")
            return root.label("قيد الفحص", "Checking")
        return text
    }

    function decisionTone(value) {
        var lower = String(value || "").toLowerCase()
        if (lower === "legit" || lower === "trusted" || lower === "accepted")
            return "success"
        if (lower === "intruder" || lower === "suspicious" || lower === "blocked")
            return "warn"
        if (lower === "unknown" || lower === "pending")
            return "info"
        return "neutral"
    }

    function sessionKindText(value) {
        var text = String(value || "")
        var lower = text.toLowerCase()
        if (lower.indexOf("protected") >= 0)
            return root.label("جلسة حماية", "Protected session")
        if (lower.indexOf("enrollment") >= 0)
            return root.label("جلسة تعلّم", "Learning session")
        if (lower.length === 0)
            return root.label("جلسة", "Session")
        return text
    }

    function trainingStatusText(session) {
        var visibility = String((session && session.training_visibility) || "not_applicable")
        if (visibility === "selected" || visibility === "supplemental_selected")
            return root.label("تساعد في التدريب", "Helps training")
        if (visibility === "counts_toward_minimum")
            return root.label("تُحتسب للتعلم", "Counts for learning")
        if (visibility === ("supplemental_" + String.fromCharCode(99, 97, 110, 100, 105, 100, 97, 116, 101)))
            return root.label("قد تساعد في التعلم", "May help learning")
        if (visibility === "blocked" || visibility === "supplemental_excluded")
            return root.label("لا تُستخدم للتعلم", "Not used for learning")
        return root.label("محفوظة محليًا", "Stored locally")
    }

    function trainingTone(session) {
        var visibility = String((session && session.training_visibility) || "not_applicable")
        if (visibility === "selected" || visibility === "supplemental_selected" || visibility === "counts_toward_minimum")
            return "success"
        if (visibility === ("supplemental_" + String.fromCharCode(99, 97, 110, 100, 105, 100, 97, 116, 101)))
            return "info"
        if (visibility === "blocked" || visibility === "supplemental_excluded")
            return "warn"
        return "neutral"
    }

    function activitySummaryText() {
        if (backend.profile && backend.profile.history_loading === true)
            return root.label("يتم تحميل السجل المحلي في الخلفية.", "Local history is loading in the background.")
        if (dashboardState.historyError)
            return root.label("تعذر تحميل السجل الكامل الآن، لكن الجلسات الحديثة تبقى ظاهرة.", "Full history could not load right now, but recent sessions remain visible.")
        if (root.sessionList.length === 0)
            return root.label("لا توجد جلسات محلية معروضة بعد.", "No local sessions are shown yet.")
        return root.label("يعرض هذا القسم آخر الجلسات بشكل مبسط بدون تفاصيل إدخال أو أدوات تحليل متقدمة.", "This page shows recent sessions in a simplified way without input details or advanced analysis tools.")
    }

    function learningSummaryText() {
        if (backend.canStartProtected === true || backend.canStop === true || runtimeState.active === true)
            return root.label("الحماية جاهزة، ويبقى السجل مرجعًا محليًا للجلسات والقرارات.", "Protection is ready, and history remains the local record for sessions and decisions.")
        if (autoEnrollment.collecting === true)
            return root.label("BioAuth يجمع جلسات موثوقة لمساعدة التعلم.", "BioAuth is collecting trusted sessions to help learning.")
        if (modelReadiness.backgroundAction === "training_in_background")
            return root.label("التدريب يعمل في الخلفية، وستظهر النتائج عند تحديث الحالة.", "Training is running in the background, and results will appear when state updates.")
        return root.label("تابع التعلّم والجاهزية من Home، واستخدم هذه الصفحة لمراجعة النشاط الأخير.", "Track learning and readiness from Home, and use this page to review recent activity.")
    }

    Component.onCompleted: root.requestFullHistory()
    onVisibleChanged: if (visible) root.requestFullHistory()

    ColumnLayout {
        id: activityContent
        width: root.availableWidth
        spacing: 18

        GlassCard {
            id: activityHeaderCard
            Layout.fillWidth: true
            implicitHeight: headerContent.implicitHeight + 36
            Layout.minimumHeight: implicitHeight

            ColumnLayout {
                id: headerContent
                anchors.fill: parent
                anchors.margins: root.compactLayout ? 16 : 20
                spacing: 14

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12

                    AssetIcon {
                        sourceUrl: root.activityIcon
                        tone: "details"
                        Layout.preferredWidth: 48
                        Layout.preferredHeight: 48
                        iconPadding: 7
                    }

                    SectionHeader {
                        Layout.fillWidth: true
                        title: root.label("النشاط", "Activity")
                        subtitle: root.activitySummaryText()
                    }

                    InfoPill {
                        visible: !root.compactLayout
                        textValue: root.label("الجلسات", "Sessions") + ": " + String(root.sessionList.length)
                        pillTone: root.sessionList.length > 0 ? "details" : "neutral"
                    }
                }

                Flow {
                    Layout.fillWidth: true
                    spacing: 10

                    InfoPill {
                        textValue: root.sessionList.length > 0 ? root.label("نشاط محلي", "Local activity") : root.label("لا يوجد نشاط", "No activity")
                        pillTone: root.sessionList.length > 0 ? "success" : "neutral"
                    }

                    InfoPill {
                        textValue: backend.profile && backend.profile.history_is_partial === true ? root.label("الأحدث فقط", "Recent only") : root.label("سجل محلي", "Local history")
                        pillTone: backend.profile && backend.profile.history_is_partial === true ? "warn" : "details"
                    }
                }

                Label {
                    Layout.fillWidth: true
                    text: root.learningSummaryText()
                    color: theme.muted
                    font.pixelSize: 13
                    wrapMode: Text.Wrap
                }
            }
        }

        Loader {
            Layout.fillWidth: true
            sourceComponent: root.sessionList.length === 0 ? emptyStateComponent : activityListComponent
        }
    }

    Component {
        id: emptyStateComponent

        GlassCard {
            Layout.fillWidth: true
            implicitHeight: emptyContent.implicitHeight + 44
            Layout.minimumHeight: implicitHeight

            ColumnLayout {
                id: emptyContent
                anchors.fill: parent
                anchors.margins: 22
                spacing: 12

                AssetIcon {
                    sourceUrl: root.sessionIcon
                    tone: "neutral"
                    Layout.preferredWidth: 56
                    Layout.preferredHeight: 56
                    Layout.alignment: Qt.AlignHCenter
                    iconPadding: 9
                }

                Label {
                    Layout.fillWidth: true
                    text: root.label("لا يوجد نشاط معروض بعد", "No activity shown yet")
                    color: theme.text
                    font.pixelSize: 22
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                }

                Label {
                    Layout.fillWidth: true
                    text: root.label("ابدأ جلسات التعلم أو الحماية من Home، وبعدها سيظهر السجل هنا بصيغة مختصرة وآمنة.", "Start learning or protection sessions from Home, then a simple safe activity record will appear here.")
                    color: theme.muted
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                }
            }
        }
    }

    Component {
        id: activityListComponent

        ListView {
            id: activityList
            clip: true
            reuseItems: true
            spacing: 12
            model: root.sessionList
            implicitHeight: Math.min(contentHeight, Math.max(360, root.height - 210))
            cacheBuffer: 360

            delegate: Rectangle {
                width: ListView.view.width
                radius: 20
                color: index % 2 === 0 ? Ui.colorToken(theme, "surface6") : Ui.colorToken(theme, "surface7")
                border.color: Ui.colorToken(theme, "border")
                border.width: 1
                implicitHeight: root.compactLayout ? compactSessionCard.implicitHeight + 24 : desktopSessionRow.implicitHeight + 24

                ColumnLayout {
                    id: compactSessionCard
                    visible: root.compactLayout
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        AssetIcon {
                            sourceUrl: root.sessionIcon
                            tone: root.decisionTone(modelData.decision)
                            Layout.preferredWidth: 40
                            Layout.preferredHeight: 40
                            iconPadding: 7
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 3

                            Label {
                                Layout.fillWidth: true
                                text: root.safeString(modelData.created_at, "—")
                                color: theme.text
                                font.bold: true
                                wrapMode: Text.Wrap
                                maximumLineCount: 2
                                elide: Text.ElideRight
                            }

                            Label {
                                Layout.fillWidth: true
                                text: root.sessionKindText(modelData.session_kind)
                                color: theme.muted
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                            }
                        }
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 8

                        InfoPill {
                            textValue: root.safeDecisionText(modelData.decision)
                            pillTone: root.decisionTone(modelData.decision)
                        }

                        InfoPill {
                            textValue: root.trainingStatusText(modelData)
                            pillTone: root.trainingTone(modelData)
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.label("التفاصيل المتقدمة وأدوات التحليل تبقى في العرض المتقدم.", "Advanced details and analysis tools stay in the advanced view.")
                        color: theme.muted
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                    }
                }

                RowLayout {
                    id: desktopSessionRow
                    visible: !root.compactLayout
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 12

                    AssetIcon {
                        sourceUrl: root.sessionIcon
                        tone: root.decisionTone(modelData.decision)
                        Layout.preferredWidth: 42
                        Layout.preferredHeight: 42
                        iconPadding: 7
                    }

                    ColumnLayout {
                        Layout.preferredWidth: 240
                        Layout.maximumWidth: 280
                        spacing: 3

                        Label {
                            Layout.fillWidth: true
                            text: root.safeString(modelData.created_at, "—")
                            color: theme.text
                            font.bold: true
                            elide: Text.ElideRight
                        }

                        Label {
                            Layout.fillWidth: true
                            text: root.sessionKindText(modelData.session_kind)
                            color: theme.muted
                            font.pixelSize: 12
                            elide: Text.ElideRight
                        }
                    }

                    InfoPill {
                        textValue: root.safeDecisionText(modelData.decision)
                        pillTone: root.decisionTone(modelData.decision)
                        Layout.preferredWidth: 160
                    }

                    InfoPill {
                        textValue: root.trainingStatusText(modelData)
                        pillTone: root.trainingTone(modelData)
                        Layout.preferredWidth: 190
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.label("محفوظ محليًا. لا تعرض هذه الصفحة تفاصيل الإدخال أو أدوات التحليل.", "Stored locally. This page does not show input details or analysis tools.")
                        color: theme.muted
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }

                    InfoPill {
                        textValue: root.label("مبسط", "Simplified")
                        pillTone: "neutral"
                    }
                }
            }
        }
    }
}
