import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property var selectedPathsMap: ({})
    property int selectionCount: 0
    readonly property var sessionList: backend.sessions
    readonly property var dashboardState: backend.dashboardState || ({})
    readonly property var runtimeState: backend.runtimeState || ({})
    readonly property var autoEnrollment: backend.autoEnrollmentState || ({})
    readonly property var modelReadiness: backend.modelReadinessState || ({})
    readonly property var productionApproval: backend.productionApprovalState || ({})
    property bool compactLayout: width < 1120

    function trx(arText, enText) { return rootWindow ? rootWindow.trx(arText, enText) : enText }
    function trainingStatusText(session) {
        var visibility = String((session && session.training_visibility) || "not_applicable")
        if (visibility === "selected")
            return trx("مستخدمة في التدريب", "Used for training")
        if (visibility === "counts_toward_minimum")
            return trx("تُحتسب للحد الأدنى", "Counts toward minimum")
        if (visibility === "supplemental_selected")
            return trx("مستخدمة كدعم إضافي", "Used as supplemental")
        if (visibility === "supplemental_candidate")
            return trx("مرشحة كدعم إضافي", "Supplemental candidate")
        if (visibility === "supplemental_excluded")
            return trx("دعم إضافي غير مستخدم", "Supplemental not used")
        if (visibility === "blocked")
            return trx("غير مقبولة للتدريب", "Not accepted for training")
        return trx("لا تنطبق", "Not applicable")
    }

    function trainingStatusTone(session) {
        return String((session && session.training_status_tone) || "neutral")
    }

    function historyStatusText() {
        var profile = backend.profile || {}
        if (profile.history_loading === true || dashboardState.historyLoading === true)
            return trx("Loading history", "Loading history")
        if (profile.history_is_partial === true)
            return trx("Recent only", "Recent only")
        if (profile.history_loaded === true)
            return trx("Full history", "Full history")
        return trx("History", "History")
    }

    function historyStatusTone() {
        var profile = backend.profile || {}
        if (profile.history_loading === true || dashboardState.historyLoading === true)
            return "info"
        if (profile.history_is_partial === true)
            return "warn"
        return "success"
    }

    function requestFullHistory() {
        if (backend && backend.loadFullHistory)
            backend.loadFullHistory()
    }

    function historyArchiveStatusVisible() {
        return runtimeState.historyFinalizing === true || String(runtimeState.historySyncWarning || "").length > 0
    }

    function historyArchiveStatusText() {
        var text = String(runtimeState.historySyncStatusText || "")
        if (text.length > 0)
            return text
        if (runtimeState.historyFinalizing === true)
            return trx("جارٍ إنهاء أرشيف الجلسة على القرص. سيظهر في السجل تلقائيًا بدون إعادة تشغيل.", "Finalizing the session archive on disk. It will appear in history automatically without restarting.")
        return trx("أرشيف الجلسة غير متاح بعد. سيتم تحديث السجل بعد كتابة الأرشيف.", "Session archive is not available yet. History will update after the archive is written.")
    }

    function historyArchiveStatusTone() {
        return String(runtimeState.historySyncWarning || "").length > 0 ? "warn" : "info"
    }

    function historyArchiveStatusTitle() {
        return runtimeState.historyFinalizing === true
               ? trx("جارٍ إنهاء الأرشيف", "Archive finalizing")
               : trx("تنبيه السجل", "History warning")
    }

    function historyLearningText() {
        if (productionApproval.protectedSessionsAvailable === true)
            return trx("الجلسات المحمية جاهزة. سيبقى السجل مرجعًا للجلسات المحلية والقرارات.", "Protected Sessions are ready. History remains the local record for sessions and decisions.")
        if (autoEnrollment.collecting === true)
            return trx("BioAuth يجمع جلسات طبيعية موثوقة بعد الموافقة، والجلسات المقبولة فقط تساعد الجاهزية.", "BioAuth is collecting natural trusted sessions after consent, and only accepted sessions help readiness.")
        if (modelReadiness.backgroundAction === "training_in_background")
            return trx("التدريب يعمل في الخلفية. السجل سيُحدّث عندما تظهر الجلسات أو نتائج جديدة.", "Training is running in the background. History will update as sessions or results appear.")
        if (productionApproval.modelStatus === "approved_for_shadow")
            return trx("النموذج في تحقق آمن. BioAuth سيجمع تحسينات مستهدفة بدون فتح الجلسات المحمية مبكرًا.", "The model is in safe validation. BioAuth will collect targeted improvements without unlocking Protected Sessions early.")
        return trx("السجل يعرض ما تم جمعه محليًا، وحالة الحماية المبسطة تظهر في صفحة الملف الشخصي.", "History shows what was collected locally, while the simplified protection status appears on the Profile page.")
    }

    function trainingReason(session) {
        var visibility = String((session && session.training_visibility) || "not_applicable")
        if (visibility === "selected" || visibility === "supplemental_selected" || visibility === "supplemental_candidate")
            return ""
        var reason = String((session && session.training_block_reason) || "")
        if (reason === "metadata_not_trusted")
            return trx("مرفوضة لأن سلامة metadata غير موثقة.", "Rejected because metadata integrity is not verified.")
        if (reason === "session_not_accepted")
            return trx("مرفوضة لأن قرار الجلسة ليس legit.", "Rejected because the session decision is not legit.")
        if (reason === "session_not_completed_normally")
            return trx("مرفوضة لأن الجلسة لم تنتهِ بشكل طبيعي.", "Rejected because the session did not end normally.")
        if (reason === "session_without_behavior_data")
            return trx("مرفوضة لأن بيانات السلوك غير كافية.", "Rejected because behavior data is insufficient.")
        if (reason === "quality_score_below_floor")
            return trx("مرفوضة لأن جودة الجلسة منخفضة.", "Rejected because the session quality is too low.")
        if (reason === "ranked_below_selection_cutoff")
            return trx("مستبعدة مؤقتًا لأن جلسات أفضل غطّت سعة التدريب.", "Excluded for now because stronger sessions already fill the training budget.")
        if (reason === "protected_session_quality_low")
            return trx("قصيرة أو ضعيفة النشاط كجلسة داعمة إضافية.", "Too short or inactive for supplemental use.")
        var detail = String((session && session.training_reason_detail) || "")
        if (detail)
            return detail
        return ""
    }
    anchors.fill: parent

    Component.onCompleted: root.requestFullHistory()
    onVisibleChanged: if (visible) root.requestFullHistory()

    function isSelected(path) {
        return !!selectedPathsMap[String(path || "")]
    }

    function toggleSelected(path, checked) {
        var key = String(path || "")
        if (!key)
            return
        if (checked && !selectedPathsMap[key]) {
            selectedPathsMap[key] = true
            selectionCount += 1
            selectedPathsMapChanged()
        } else if (!checked && selectedPathsMap[key]) {
            delete selectedPathsMap[key]
            selectionCount = Math.max(0, selectionCount - 1)
            selectedPathsMapChanged()
        }
    }

    function clearSelection() {
        selectedPathsMap = ({})
        selectionCount = 0
    }

    function selectedPaths() {
        var out = []
        for (var key in selectedPathsMap) {
            if (selectedPathsMap[key])
                out.push(key)
        }
        return out
    }

    function selectAllVisible() {
        var next = ({})
        for (var i = 0; i < root.sessionList.length; ++i) {
            var item = root.sessionList[i]
            if (item && item.path)
                next[String(item.path)] = true
        }
        selectedPathsMap = next
    }

    function allVisibleSelected() {
        if (root.sessionList.length === 0)
            return false
        for (var i = 0; i < root.sessionList.length; ++i) {
            var item = root.sessionList[i]
            if (!item || !item.path || !selectedPathsMap[String(item.path)])
                return false
        }
        return true
    }

    function pruneSelection() {
        var allowed = ({})
        var next = ({})
        for (var i = 0; i < root.sessionList.length; ++i) {
            var item = root.sessionList[i]
            if (item && item.path)
                allowed[String(item.path)] = true
        }
        for (var key in selectedPathsMap) {
            if (selectedPathsMap[key] && allowed[key])
                next[key] = true
        }
        selectedPathsMap = next
    }

    Connections {
        target: backend
        function onSessionsChanged() {
            root.pruneSelection()
        }
    }

    GlassCard {
        anchors.fill: parent

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: root.compactLayout ? 14 : 20
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                SectionHeader {
                    Layout.fillWidth: true
                    title: backend.tr("history")
                    subtitle: trx("صار بإمكانك تحديد أكثر من جلسة ثم حذفها دفعة واحدة من نفس شاشة السجل.", "You can now select multiple sessions and remove them in one step from the same history view.")
                }
                InfoPill {
                    textValue: trx("Sessions", "Sessions") + ": " + root.sessionList.length
                    pillTone: "details"
                }
                InfoPill {
                    textValue: root.historyStatusText()
                    pillTone: root.historyStatusTone()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                radius: 18
                color: theme.surface1
                border.color: theme.border
                border.width: 1
                implicitHeight: learningHistoryColumn.implicitHeight + 24

                ColumnLayout {
                    id: learningHistoryColumn
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 7
                    Label {
                        Layout.fillWidth: true
                        text: trx("Automated learning record", "Automated learning record")
                        color: theme.text
                        font.bold: true
                        wrapMode: Text.Wrap
                    }
                    Label {
                        Layout.fillWidth: true
                        text: historyLearningText()
                        color: theme.muted
                        wrapMode: Text.Wrap
                    }
                }
            }

            GlassCard {
                Layout.fillWidth: true
                radius: 22
                color: root.selectionCount > 0
                       ? (theme.surface2)
                       : (theme.surface4)
                border.color: root.selectionCount > 0
                              ? Qt.rgba(theme.info.r, theme.info.g, theme.info.b, 0.9)
                              : theme.border
                implicitHeight: selectionTray.implicitHeight + 28

                Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.margins: 10
                    width: 4
                    radius: 2
                    color: root.selectionCount > 0 ? theme.info : Qt.rgba(theme.info.r, theme.info.g, theme.info.b, 0.35)
                }

                ColumnLayout {
                    id: selectionTray
                    anchors.fill: parent
                    anchors.margins: 14
                    anchors.leftMargin: 22
                    spacing: 12

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        Label {
                            Layout.fillWidth: true
                            text: trx("Archive actions", "Archive actions")
                            color: theme.text
                            font.bold: true
                            wrapMode: Text.Wrap
                        }
                        InfoPill {
                            textValue: trx("Selected", "Selected") + ": " + root.selectionCount
                            pillTone: root.selectionCount > 0 ? "warn" : "details"
                        }
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 10
                        AppButton {
                            text: trx("تحديد الكل", "Select all")
                            role: "details"
                            compact: true
                            enabled: root.sessionList.length > 0 && !root.allVisibleSelected()
                            onClicked: root.selectAllVisible()
                        }
                        AppButton {
                            text: trx("مسح التحديد", "Clear selection")
                            role: "neutral"
                            compact: true
                            enabled: root.selectionCount > 0
                            onClicked: root.clearSelection()
                        }
                        AppButton {
                            text: trx("حذف المحدد", "Delete selected")
                            role: "danger"
                            compact: true
                            enabled: root.selectionCount > 0 && !root.dashboardState.historyLoading
                            onClicked: rootWindow.requestDeleteSessions(root.selectedPaths())
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.selectionCount > 0
                              ? trx("الحذف سيؤثر فقط على العناصر المحددة من الأرشيف المحلي.", "Delete will only affect the selected items from the local archive.")
                              : trx("اختر الجلسات التي تريد تنظيفها من الأرشيف المحلي ثم استخدم إجراءات الدفعة.", "Select the sessions you want to clean from the local archive, then use the batch actions.")
                        color: theme.muted
                        wrapMode: Text.Wrap
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                visible: !root.compactLayout
                radius: 18
                color: theme.surface1
                border.color: Qt.rgba(theme.info.r, theme.info.g, theme.info.b, 0.32)
                border.width: 1
                implicitHeight: 56

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 12
                    AppCheckBox {
                        compact: true
                        checked: root.allVisibleSelected()
                        enabled: root.sessionList.length > 0
                        onToggled: {
                            if (checked)
                                root.selectAllVisible()
                            else
                                root.clearSelection()
                        }
                    }
                    Label { text: trx("Date", "Date"); color: theme.muted; font.bold: true; Layout.preferredWidth: 220 }
                    Label { text: trx("Type", "Type"); color: theme.muted; font.bold: true; Layout.preferredWidth: 150 }
                    Label { text: trx("Decision", "Decision"); color: theme.muted; font.bold: true; Layout.preferredWidth: 160 }
                    Label { text: trx("Rows", "Rows"); color: theme.muted; font.bold: true; Layout.preferredWidth: 140 }
                    Item { Layout.fillWidth: true }
                    Label { text: trx("Actions", "Actions"); color: theme.muted; font.bold: true }
                }
            }

            Label {
                Layout.fillWidth: true
                visible: backend.profile.history_loading === true || dashboardState.historyLoading === true || backend.profile.history_is_partial === true || dashboardState.historyError
                text: dashboardState.historyError
                      ? trx("تعذر تحميل السجل الكامل الآن. ستبقى الجلسات الحديثة ظاهرة.", "Full history could not load right now. Recent sessions remain visible.")
                      : (backend.profile.history_loading === true || dashboardState.historyLoading === true
                         ? trx("يتم تحميل السجل الكامل في الخلفية بدون إيقاف الواجهة.", "Full history is loading in the background without blocking the UI.")
                         : trx("تظهر أحدث الجلسات الآن، وسيظهر السجل الكامل عند انتهاء التحميل.", "Recent sessions are visible now; the full history appears when loading finishes."))
                color: theme.muted
                wrapMode: Text.Wrap
            }

            Rectangle {
                Layout.fillWidth: true
                visible: root.historyArchiveStatusVisible()
                radius: 16
                color: theme.surface2
                border.color: rootWindow ? rootWindow.toneColor(root.historyArchiveStatusTone()) : theme.border
                border.width: 1
                implicitHeight: archiveStatusColumn.implicitHeight + 24

                ColumnLayout {
                    id: archiveStatusColumn
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 6

                    Label {
                        Layout.fillWidth: true
                        text: root.historyArchiveStatusTitle()
                        color: rootWindow ? rootWindow.toneColor(root.historyArchiveStatusTone()) : theme.text
                        font.bold: true
                        wrapMode: Text.Wrap
                    }
                    Label {
                        Layout.fillWidth: true
                        text: root.historyArchiveStatusText()
                        color: theme.muted
                        wrapMode: Text.Wrap
                    }
                }
            }

            Loader {
                Layout.fillWidth: true
                Layout.fillHeight: true
                sourceComponent: root.sessionList.length === 0 ? emptyState : historyTable
            }
        }
    }

    Component {
        id: emptyState
        Item {
            implicitHeight: 260
            ColumnLayout {
                anchors.centerIn: parent
                spacing: 12
                Label {
                    text: backend.tr("history_empty")
                    color: theme.muted
                    font.pixelSize: 18
                    font.bold: true
                }
                AppButton {
                    objectName: "historyStartEnrollmentLoggerButton"
                    text: backend.tr("start_enrollment_logger")
                    role: "primary"
                    enabled: backend.canStartEnrollmentLogger
                    ToolTip.visible: hovered && !enabled && backend.startEnrollmentLoggerUnavailableReason.length > 0
                    ToolTip.text: backend.startEnrollmentLoggerUnavailableReason
                    ToolTip.delay: 100
                    onClicked: backend.startEnrollment()
                }
                AppButton {
                    objectName: "historyStopEnrollmentLoggerButton"
                    text: backend.tr("stop_enrollment_logger")
                    role: "danger"
                    enabled: backend.canStopEnrollmentLogger
                    ToolTip.visible: hovered && !enabled && backend.stopEnrollmentLoggerUnavailableReason.length > 0
                    ToolTip.text: backend.stopEnrollmentLoggerUnavailableReason
                    ToolTip.delay: 100
                    onClicked: backend.stopEnrollmentLogger(false)
                }
            }
        }
    }

    Component {
        id: historyTable
        ListView {
            clip: true
            spacing: 10
            model: root.sessionList
            reuseItems: true
            cacheBuffer: 480

            delegate: Rectangle {
                width: ListView.view.width
                radius: 18
                readonly property bool rowSelected: root.isSelected(modelData.path)
                color: rowSelected
                       ? (theme.navActiveBg)
                       : (index % 2 === 0 ? (theme.surface6) : (theme.surface7))
                border.color: rowSelected ? Qt.rgba(theme.info.r, theme.info.g, theme.info.b, 0.72) : theme.border
                border.width: 1
                implicitHeight: root.compactLayout ? compactCard.implicitHeight + 24 : desktopRow.implicitHeight + 24

                ColumnLayout {
                    id: compactCard
                    visible: root.compactLayout
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        AppCheckBox {
                            compact: true
                            checked: rowSelected
                            onToggled: root.toggleSelected(modelData.path, checked)
                        }
                        Label {
                            text: modelData.created_at || "—"
                            color: theme.text
                            font.bold: true
                            wrapMode: Text.Wrap
                            Layout.fillWidth: true
                        }
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        InfoPill {
                            textValue: trx("Type", "Type") + ": " + (modelData.session_kind || "—")
                            pillTone: "details"
                        }
                        InfoPill {
                            textValue: trx("Decision", "Decision") + ": " + (modelData.decision || "—")
                            pillTone: rootWindow.decisionTone(modelData.decision)
                        }
                        InfoPill {
                            textValue: root.trainingStatusText(modelData)
                            pillTone: root.trainingStatusTone(modelData)
                        }
                    }

                    Label {
                        text: trx("Rows", "Rows") + ": K " + (modelData.keyboard_rows || 0) + "  ·  M " + (modelData.mouse_rows || 0)
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Label {
                        visible: !!root.trainingReason(modelData)
                        text: root.trainingReason(modelData)
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 8
                        AppButton {
                            text: trx("Details", "Details")
                            role: "details"
                            compact: true
                            onClicked: rootWindow.openSessionDetails(modelData.path)
                        }
                        AppButton {
                            text: trx("Analyze", "Analyze")
                            role: "analyze"
                            compact: true
                            onClicked: rootWindow.openSessionDetails(modelData.path)
                        }
                        AppButton {
                            text: trx("Delete", "Delete")
                            role: "danger"
                            compact: true
                            onClicked: rootWindow.requestDeleteSession(modelData.path)
                        }
                    }
                }

                RowLayout {
                    id: desktopRow
                    visible: !root.compactLayout
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 12
                    AppCheckBox {
                        compact: true
                        checked: rowSelected
                        onToggled: root.toggleSelected(modelData.path, checked)
                    }
                    Label {
                        text: modelData.created_at || "—"
                        color: theme.text
                        font.bold: true
                        Layout.preferredWidth: 220
                        elide: Text.ElideRight
                    }
                    InfoPill {
                        textValue: modelData.session_kind || "—"
                        pillTone: "details"
                        Layout.preferredWidth: 150
                    }
                    InfoPill {
                        textValue: modelData.decision || "—"
                        pillTone: rootWindow.decisionTone(modelData.decision)
                        Layout.preferredWidth: 160
                    }
                    InfoPill {
                        textValue: root.trainingStatusText(modelData)
                        pillTone: root.trainingStatusTone(modelData)
                        Layout.preferredWidth: 210
                    }
                    Label {
                        text: "K " + (modelData.keyboard_rows || 0) + "  ·  M " + (modelData.mouse_rows || 0)
                        color: theme.muted
                        Layout.preferredWidth: 140
                    }
                    Item { Layout.fillWidth: true }
                    RowLayout {
                        spacing: 8
                        AppButton {
                            text: trx("Details", "Details")
                            role: "details"
                            compact: true
                            onClicked: rootWindow.openSessionDetails(modelData.path)
                        }
                        AppButton {
                            text: trx("Analyze", "Analyze")
                            role: "analyze"
                            compact: true
                            onClicked: rootWindow.openSessionDetails(modelData.path)
                        }
                        AppButton {
                            text: trx("Delete", "Delete")
                            role: "danger"
                            compact: true
                            onClicked: rootWindow.requestDeleteSession(modelData.path)
                        }
                    }
                }
            }
        }
    }
}
