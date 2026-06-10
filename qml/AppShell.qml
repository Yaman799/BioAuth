import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "components"
import "pages"

Item {
    id: shell
    property var windowRef
    property var theme: windowRef ? windowRef.theme : backend.theme
    property int navSelection: 0
    property bool liveLoaded: false
    property bool profileLoaded: false
    property bool modelEvaluationLoaded: false
    property bool historyLoaded: false
    property bool driftLoaded: false
    property bool settingsLoaded: false
    property bool compactLayout: windowRef ? windowRef.compactWidth : width < 1180
    property bool denseLayout: windowRef ? windowRef.denseWidth : width < 980
    property bool sidebarAsDrawer: (windowRef ? windowRef.width : width) < 1100
    property real sidebarWidth: windowRef ? windowRef.shellSidebarWidth : (denseLayout ? 208 : (compactLayout ? 244 : 304))
    property real drawerWidth: Math.min(Math.max(264, sidebarWidth), Math.max(264, width - 48))
    property int _lastNavSelection: navSelection
    property int _pageSlideDirection: 1
    readonly property var dashboardState: backend.dashboardState || ({})

    onNavSelectionChanged: {
        _pageSlideDirection = navSelection >= _lastNavSelection ? 1 : -1
        _lastNavSelection = navSelection
        if (contentPageMotion.running)
            contentPageMotion.stop()
        contentPageMotion.start()
        if (navSelection === 1)
            liveLoaded = true
        else if (navSelection === 2)
            profileLoaded = true
        else if (navSelection === 3)
            modelEvaluationLoaded = true
        else if (navSelection === 4)
            historyLoaded = true
        else if (navSelection === 5)
            driftLoaded = true
        else if (navSelection === 6)
            settingsLoaded = true
        if (navDrawer.opened)
            navDrawer.close()
    }

    function trx(arText, enText) { return windowRef ? windowRef.trx(arText, enText) : enText }
    function toneColor(tone) { return windowRef ? windowRef.toneColor(tone) : theme.info }
    function decisionTone(decision) { return windowRef ? windowRef.decisionTone(decision) : "info" }
    function driftTone(kind) { return windowRef ? windowRef.driftTone(kind) : "neutral" }
    function driftLabel(kind) { return windowRef ? windowRef.driftLabel(kind) : "" }
    function driftDescription(kind) { return windowRef ? windowRef.driftDescription(kind) : "" }
    function openSessionDetails(path) { if (windowRef) windowRef.openSessionDetails(path) }
    function requestDeleteSession(path) { if (windowRef) windowRef.requestDeleteSession(path) }
    function openResetProfileConfirm() { if (windowRef) windowRef.openResetProfileConfirm() }
    function openDeleteAccountConfirm(password) { if (windowRef) windowRef.openDeleteAccountConfirm(password) }
    function openDeleteMyDataConfirm() { if (windowRef) windowRef.openDeleteMyDataConfirm() }
    function openDeleteIncidentEvidenceConfirm() { if (windowRef) windowRef.openDeleteIncidentEvidenceConfirm() }
    readonly property string currentPageTitle: {
        if (navSelection === 0) return trx("نظرة عامة", "Overview")
        if (navSelection === 1) return trx("الجلسة الحية", "Live Session")
        if (navSelection === 2) return trx("الملف والتدريب", "Profile & Training")
        if (navSelection === 3) return trx("تقييم المودلات", "Model Evaluation")
        if (navSelection === 4) return trx("الجلسات والبيانات", "Sessions & Data")
        if (navSelection === 5) return trx("مختبر الانحراف", "Drift Lab")
        return backend.tr("settings")
    }
    readonly property string currentPageSubtitle: {
        if (navSelection === 0) return trx("ملخص الحالة الحالية وجهوزية الملف السلوكي.", "Current system status and profile readiness.")
        if (navSelection === 1) return trx("الحالة الحالية للجلسة المحمية وقراءات المراقبة.", "Current protected session status and monitor telemetry.")
        if (navSelection === 2) return trx("إدارة التهيئة والتدريب وجهوزية ملفك السلوكي.", "Manage enrollment, training, and behavioral profile readiness.")
        if (navSelection === 3) return trx("مكان مخصص لاحقًا لتقارير EER وFAR وFRR والعتبات، بدون رسوم أو بيانات وهمية.", "Dedicated future surface for EER, FAR, FRR, and threshold reports, with no fake charts or data.")
        if (navSelection === 4) return trx("استعرض الجلسات السابقة وافتح تفاصيل كل جلسة.", "Review saved sessions and inspect detailed session metadata.")
        if (navSelection === 5) return trx("عرض readiness وحالة الجلسة وshadow lifecycle فقط.", "Readiness, live session state, and shadow lifecycle only.")
        return backend.tr("settings_subtitle")
    }

    function dashboardStateText() {
        var state = dashboardState || ({})
        if (state.lastRefreshError)
            return trx("تحتاج المزامنة انتباهًا", "Refresh needs attention")
        if (state.loading)
            return trx("تحميل لوحة المعلومات", "Loading dashboard")
        if (state.historyLoading)
            return trx("تحميل السجل", "Loading history")
        if (state.updating)
            return trx("تحديث بالخلفية", "Updating in background")
        if (state.stale)
            return trx("يعرض بيانات محفوظة", "Showing cached data")
        // Keep backend refresh timing available for debug/telemetry, but do not
        // render a changing timestamp/duration in the main dashboard header.
        return ""
    }

    function dashboardStateTone() {
        var state = dashboardState || ({})
        if (state.lastRefreshError)
            return "warn"
        if (state.loading || state.historyLoading || state.updating)
            return "info"
        if (state.stale)
            return "warn"
        return "details"
    }

    ListModel {
        id: navModel
        ListElement { navIndex: 0; glyph: "◉"; title: ""; note: "" }
        ListElement { navIndex: 1; glyph: "◎"; title: ""; note: "" }
        ListElement { navIndex: 2; glyph: "◌"; title: ""; note: "" }
        ListElement { navIndex: 3; glyph: "Σ"; title: ""; note: "" }
        ListElement { navIndex: 4; glyph: "≣"; title: ""; note: "" }
        ListElement { navIndex: 5; glyph: "∆"; title: ""; note: "" }
        ListElement { navIndex: 6; glyph: "⚙"; title: ""; note: "" }
    }

    function refreshNavModel() {
        navModel.setProperty(0, "title", trx("Overview", "Overview"))
        navModel.setProperty(0, "note", trx("الحالة والجاهزية", "Status & readiness"))
        navModel.setProperty(1, "title", trx("Live Session", "Live Session"))
        navModel.setProperty(1, "note", trx("المراقبة والقرار", "Monitor & decision"))
        navModel.setProperty(2, "title", trx("Profile & Training", "Profile & Training"))
        navModel.setProperty(2, "note", trx("التهيئة والتدريب", "Enrollment & training"))
        navModel.setProperty(3, "title", trx("Model Evaluation", "Model Evaluation"))
        navModel.setProperty(3, "note", trx("Placeholder فقط", "Placeholder only"))
        navModel.setProperty(4, "title", trx("Sessions & Data", "Sessions & Data"))
        navModel.setProperty(4, "note", trx("الأرشيف والتفاصيل", "Archive & details"))
        navModel.setProperty(5, "title", trx("Drift Lab", "Drift Lab"))
        navModel.setProperty(5, "note", trx("معاينة تجريبية", "Experimental preview"))
        navModel.setProperty(6, "title", trx("Settings", "Settings"))
        navModel.setProperty(6, "note", trx("التفضيلات والتشغيل", "Preferences & startup"))
    }

    Component.onCompleted: refreshNavModel()

    Connections {
        target: backend
        function onLanguageChanged() { shell.refreshNavModel() }
    }

    anchors.fill: parent

    Component {
        id: navigationPanelComponent

        ScrollView {
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            Item {
                width: parent.width
                implicitHeight: sidebarColumn.implicitHeight + 18

                ColumnLayout {
                    id: sidebarColumn
                    width: parent.width
                    spacing: shell.denseLayout ? 10 : 14

                    Rectangle {
                        Layout.fillWidth: true
                        radius: shell.denseLayout ? 18 : 24
                        implicitHeight: userCardColumn.implicitHeight + 28
                        color: theme.userCardBg || theme.surface2
                        border.color: theme.border

                        ColumnLayout {
                            id: userCardColumn
                            anchors.fill: parent
                            anchors.margins: shell.denseLayout ? 14 : 18
                            spacing: 8

                            Label {
                                text: backend.currentUser.display_name || backend.currentUser.user_id || "BioAuth"
                                color: theme.text
                                font.pixelSize: shell.denseLayout ? 20 : 24
                                font.bold: true
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }
                            Label {
                                visible: !!backend.currentUser.display_name && !!backend.currentUser.user_id && backend.currentUser.display_name !== backend.currentUser.user_id
                                text: backend.currentUser.user_id || ""
                                color: theme.muted
                                font.pixelSize: 13
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }
                            Flow {
                                Layout.fillWidth: true
                                spacing: 8
                                InfoPill {
                                    textValue: backend.runtimeState.activeText || backend.tr("status_idle")
                                    pillTone: backend.runtimeState.active ? (backend.runtimeState.statusTone || backend.statusTone) : backend.statusTone
                                }
                                InfoPill {
                                    textValue: backend.profile.readyText || "—"
                                    pillTone: backend.profile.ready ? "success" : "warn"
                                }
                                InfoPill {
                                    textValue: backend.profile.lockReadinessText || backend.tr("lock_readiness_warning_only_short")
                                    pillTone: backend.profile.lockReadinessTone || "warn"
                                }
                                InfoPill {
                                    textValue: String((backend.licenseStatus && backend.licenseStatus.effective_tier) || "basic").toUpperCase()
                                    pillTone: (backend.licenseStatus && backend.licenseStatus.premium_active) ? "success" : "info"
                                }
                            }
                        }
                    }

                    Repeater {
                        model: navModel
                        delegate: Rectangle {
                            Layout.fillWidth: true
                            radius: 18
                            implicitHeight: shell.denseLayout ? 62 : 78
                            color: navSelection === navIndex ? (theme.navActiveBg || theme.surface2) : "transparent"
                            border.color: navSelection === navIndex ? theme.accent : "transparent"
                            border.width: 1

                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: shell.denseLayout ? 10 : 12
                                spacing: shell.denseLayout ? 10 : 12

                                Rectangle {
                                    implicitWidth: shell.denseLayout ? 36 : 42
                                    implicitHeight: shell.denseLayout ? 36 : 42
                                    radius: shell.denseLayout ? 12 : 14
                                    color: navSelection === navIndex ? theme.accent : (theme.navIconBg || theme.surface1)

                                    Label {
                                        anchors.centerIn: parent
                                        text: glyph
                                        color: navSelection === navIndex ? theme.chipText : theme.text
                                        font.pixelSize: shell.denseLayout ? 16 : 19
                                        font.bold: true
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2

                                    Label {
                                        text: title
                                        color: theme.text
                                        font.bold: true
                                        font.pixelSize: shell.denseLayout ? 14 : 15
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                    Label {
                                        visible: !shell.denseLayout
                                        text: note
                                        color: theme.muted
                                        font.pixelSize: 12
                                        wrapMode: Text.Wrap
                                        Layout.fillWidth: true
                                    }
                                }
                            }

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: navSelection = navIndex
                            }

                            Behavior on color { ColorAnimation { duration: 160; easing.type: Easing.OutCubic } }
                            Behavior on border.color { ColorAnimation { duration: 160; easing.type: Easing.OutCubic } }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        AppButton {
                            text: backend.tr("about_us")
                            role: "details"
                            compact: shell.denseLayout
                            Layout.fillWidth: true
                            onClicked: backend.openAboutUs()
                        }
                        AppButton {
                            text: window.trx("إنشاء حزمة دعم", "Create support bundle")
                            role: "details"
                            compact: shell.denseLayout
                            Layout.fillWidth: true
                            onClicked: backend.exportSupportBundle()
                        }
                        AppButton {
                            text: backend.tr("logout")
                            role: "warn"
                            compact: shell.denseLayout
                            Layout.fillWidth: true
                            onClicked: backend.logout()
                        }
                    }
                }
            }
        }
    }

    Drawer {
        id: navDrawer
        parent: Overlay.overlay
        edge: Qt.LeftEdge
        modal: true
        interactive: shell.sidebarAsDrawer
        visible: shell.sidebarAsDrawer
        width: shell.drawerWidth
        height: shell.height
        padding: 0
        background: Rectangle {
            color: theme.surface3
            border.color: theme.border
        }

        Loader {
            anchors.fill: parent
            anchors.margins: 12
            active: shell.sidebarAsDrawer
            asynchronous: true
            sourceComponent: navigationPanelComponent
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: shell.denseLayout ? 12 : 20
        spacing: shell.denseLayout ? 12 : 18

        GlassCard {
            visible: !shell.sidebarAsDrawer
            Layout.preferredWidth: shell.sidebarWidth
            Layout.minimumWidth: Math.max(188, shell.sidebarWidth - 16)
            Layout.maximumWidth: shell.sidebarWidth
            Layout.fillHeight: true

            Loader {
                anchors.fill: parent
                anchors.margins: 0
                active: !shell.sidebarAsDrawer
                asynchronous: true
                sourceComponent: navigationPanelComponent
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: shell.denseLayout ? 12 : 18

            GlassCard {
                Layout.fillWidth: true
                implicitHeight: headerColumn.implicitHeight + (shell.denseLayout ? 24 : 32)

                ColumnLayout {
                    id: headerColumn
                    anchors.fill: parent
                    anchors.margins: shell.denseLayout ? 16 : 22
                    spacing: 12

                    Label {
                        text: currentPageTitle
                        color: theme.text
                        font.pixelSize: shell.denseLayout ? 24 : 30
                        font.bold: true
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Label {
                        text: currentPageSubtitle
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 10

                        AppButton {
                            visible: shell.sidebarAsDrawer
                            text: trx("القائمة", "Menu")
                            role: "details"
                            compact: true
                            onClicked: navDrawer.open()
                        }
                        InfoPill {
                            textValue: trx("Trust", "Trust") + ": " + (backend.runtimeState.trustLabel || backend.runtimeState.decisionLabel || backend.runtimeState.decisionText || backend.tr("status_idle"))
                            pillTone: backend.runtimeState.active ? (backend.runtimeState.trustTone || decisionTone(backend.runtimeState.decisionText)) : backend.statusTone
                        }
                        InfoPill {
                            textValue: trx("Elapsed", "Elapsed") + ": " + (backend.runtimeState.elapsed || "--")
                            pillTone: "details"
                        }
                        RowLayout {
                            visible: shell.dashboardStateText().length > 0
                            spacing: 6
                            BusyIndicator {
                                visible: !!(shell.dashboardState.loading || shell.dashboardState.updating || shell.dashboardState.historyLoading)
                                running: visible
                                implicitWidth: 18
                                implicitHeight: 18
                            }
                            InfoPill {
                                textValue: shell.dashboardStateText()
                                pillTone: shell.dashboardStateTone()
                            }
                        }
                        AppButton {
                            text: windowRef && windowRef.visibility === Window.FullScreen ? trx("Exit Full Screen", "Exit Full Screen") : trx("Full Screen", "Full Screen")
                            role: "neutral"
                            compact: true
                            onClicked: if (windowRef) windowRef.toggleFullscreen()
                        }
                    }
                }
            }

            Item {
                id: contentPageViewport
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true

                StackLayout {
                    id: contentPageStack
                    anchors.fill: parent
                    currentIndex: navSelection

                    Loader {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        active: true
                        asynchronous: true
                        sourceComponent: overviewPageComponent
                    }
                    Loader {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        active: shell.liveLoaded || navSelection === 1
                        asynchronous: true
                        sourceComponent: livePageComponent
                    }
                    Loader {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        active: shell.profileLoaded || navSelection === 2
                        asynchronous: true
                        sourceComponent: profilePageComponent
                    }
                    Loader {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        active: shell.modelEvaluationLoaded || navSelection === 3
                        asynchronous: true
                        sourceComponent: modelEvaluationPageComponent
                    }
                    Loader {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        active: shell.historyLoaded || navSelection === 4
                        asynchronous: true
                        sourceComponent: historyPageComponent
                    }
                    Loader {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        active: shell.driftLoaded || navSelection === 5
                        asynchronous: true
                        sourceComponent: driftPageComponent
                    }
                    Loader {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        active: shell.settingsLoaded || navSelection === 6
                        asynchronous: true
                        sourceComponent: settingsPageComponent
                    }
                }

                ParallelAnimation {
                    id: contentPageMotion
                    NumberAnimation {
                        target: contentPageStack
                        property: "opacity"
                        from: 0.72
                        to: 1.0
                        duration: 220
                        easing.type: Easing.OutCubic
                    }
                    NumberAnimation {
                        target: contentPageStack
                        property: "x"
                        from: shell._pageSlideDirection * (shell.denseLayout ? 14 : 28)
                        to: 0
                        duration: 240
                        easing.type: Easing.OutCubic
                    }
                }
            }

            Component { id: overviewPageComponent; OverviewPage { rootWindow: shell } }
            Component { id: livePageComponent; LiveSessionPage { rootWindow: shell } }
            Component { id: profilePageComponent; ProfilePage { rootWindow: shell } }
            Component { id: modelEvaluationPageComponent; ModelEvaluationPage { rootWindow: shell } }
            Component { id: historyPageComponent; HistoryPage { rootWindow: shell } }
            Component { id: driftPageComponent; DriftLabPage { rootWindow: shell } }
            Component { id: settingsPageComponent; SettingsPage { rootWindow: shell } }
        }
    }
}
