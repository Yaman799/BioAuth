import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"
import "pages/user"
import "theme/Ui.js" as Ui

Item {
    id: shell
    property var windowRef
    property var theme: windowRef ? windowRef.theme : backend.theme
    property int navSelection: 0
    property bool compactLayout: windowRef ? windowRef.compactWidth : width < 1180
    property bool denseLayout: windowRef ? windowRef.denseWidth : width < 980
    property bool sidebarAsDrawer: (windowRef ? windowRef.width : width) < 1100
    property real sidebarWidth: windowRef ? windowRef.shellSidebarWidth : (denseLayout ? 208 : (compactLayout ? 244 : 304))
    property real drawerWidth: Math.min(Math.max(264, sidebarWidth), Math.max(264, width - 48))
    property int _lastNavSelection: navSelection
    property int _pageSlideDirection: 1

    readonly property url brandLogo: Qt.resolvedUrl("assets/brand/bioauth_app_logo.png")
    readonly property url homeIcon: Qt.resolvedUrl("assets/bioauth/user_icons/01_home.png")
    readonly property url protectionIcon: Qt.resolvedUrl("assets/bioauth/user_icons/02_protection_shield.png")
    readonly property url updatesIcon: Qt.resolvedUrl("assets/bioauth/user_icons/04_updates_refresh.png")
    readonly property url faceIcon: Qt.resolvedUrl("assets/bioauth/user_icons/03_face_scan.png")
    readonly property url settingsIcon: Qt.resolvedUrl("assets/bioauth/user_icons/05_settings_gear.png")
    readonly property url activityIcon: Qt.resolvedUrl("assets/bioauth/user_icons/08_activity_history.png")
    readonly property url privacyIcon: Qt.resolvedUrl("assets/bioauth/user_icons/06_privacy_lock.png")

    onNavSelectionChanged: {
        _pageSlideDirection = navSelection >= _lastNavSelection ? 1 : -1
        _lastNavSelection = navSelection
        if (contentPageMotion.running)
            contentPageMotion.stop()
        contentPageMotion.start()
        if (navDrawer.opened)
            navDrawer.close()
    }

    function pageTitleKey(index) {
        if (index === 1) return "user_shell_protection"
        if (index === 2) return "user_shell_model_update"
        if (index === 3) return "user_shell_face"
        if (index === 4) return "user_shell_settings"
        if (index === 5) return "user_shell_activity"
        return "user_shell_home"
    }

    function pageNoteKey(index) {
        if (index === 1) return "user_shell_protection_note"
        if (index === 2) return "user_shell_model_update_note"
        if (index === 3) return "user_shell_face_note"
        if (index === 4) return "user_shell_settings_note"
        if (index === 5) return "user_shell_activity_note"
        return "user_shell_home_note"
    }

    function navIcon(index) {
        if (index === 1) return protectionIcon
        if (index === 2) return updatesIcon
        if (index === 3) return faceIcon
        if (index === 4) return settingsIcon
        if (index === 5) return activityIcon
        return homeIcon
    }

    function navTitle(index, titleKey) {
        if (index === 5)
            return Ui.trx(backend.language === "ar", "النشاط", "Activity")
        return backend.tr(titleKey || pageTitleKey(index))
    }

    function navNote(index, noteKey) {
        if (index === 5)
            return Ui.trx(backend.language === "ar", "سجل مبسط وآمن", "Simple safe history")
        return backend.tr(noteKey || pageNoteKey(index))
    }

    function userSafeStatusText(value, fallbackText) {
        // Delegate to backend-side filter (src/bioauth/ui_state/safe_text.py).
        // backend.safeStatusMessage is always filtered; for other values keep
        // the keyword guard as a defence-in-depth fallback.
        var text = String(value || "")
        if (text.length === 0)
            return fallbackText || ""
        if (backend.userSafeStatusText !== undefined)
            return backend.userSafeStatusText(text, fallbackText || "")
        if (text === backend.statusMessage && backend.safeStatusMessage !== undefined)
            return backend.safeStatusMessage || fallbackText || ""
        var lower = text.toLowerCase()
        var statusTerms = []
        var hasFilteredTerm = false
        for (var i = 0; i < statusTerms.length; i++) {
            if (lower.indexOf(statusTerms[i]) >= 0) {
                hasFilteredTerm = true
                break
            }
        }
        if (hasFilteredTerm) {
            if (lower.indexOf("suspicious") >= 0 || lower.indexOf("attention") >= 0)
                return Ui.trx(backend.language === "ar", "فحص الحماية يحتاج انتباهًا", "Background check needs attention")
            if (lower.indexOf("pending") >= 0 || lower.indexOf("waiting") >= 0 || lower.indexOf("collecting") >= 0)
                return Ui.trx(backend.language === "ar", "فحص الحماية جارٍ", "Background check in progress")
            return Ui.trx(backend.language === "ar", "فحص الحماية نشط", "Background check active")
        }
        return text
    }

    function compactUserStatusText(value, fallbackText) {
        var text = shell.userSafeStatusText(value, fallbackText || Ui.trx(backend.language === "ar", "Ù‡Ø§Ø¯Ø¦", "Idle"))
        var lower = text.toLowerCase()
        if (text.length === 0)
            return fallbackText || Ui.trx(backend.language === "ar", "هادئ", "Idle")
        if (lower.indexOf("suspicious") >= 0 ||
                lower.indexOf("intruder") >= 0 ||
                lower.indexOf("blocked") >= 0 ||
                lower.indexOf("error") >= 0 ||
                lower.indexOf("fail") >= 0 ||
                lower.indexOf("attention") >= 0)
            return Ui.trx(backend.language === "ar", "يحتاج انتباهًا", "Needs attention")
        if (lower.indexOf("pending") >= 0 ||
                lower.indexOf("waiting") >= 0 ||
                lower.indexOf("collecting") >= 0)
            return Ui.trx(backend.language === "ar", "يفحص", "Checking")
        if (backend.runtimeState.active)
            return Ui.trx(backend.language === "ar", "نشط", "Active")
        return fallbackText || Ui.trx(backend.language === "ar", "هادئ", "Idle")
    }

    function activePageLoader() {
        if (navSelection === 0) return userHomeLoader
        if (navSelection === 1) return userProtectionLoader
        if (navSelection === 2) return userModelUpdateLoader
        if (navSelection === 3) return userFaceLoader
        if (navSelection === 4) return userSettingsLoader
        if (navSelection === 5) return userActivityLoader
        return null
    }

    function tourTarget(name) {
        var loader = activePageLoader()
        if (!loader || !loader.item || typeof loader.item.tourTarget !== "function")
            return null
        return loader.item.tourTarget(name)
    }

    function scrollToTourTarget(name) {
        var loader = activePageLoader()
        if (!loader || !loader.item)
            return false

        var page = loader.item
        if (typeof page.scrollToTourTarget === "function")
            return page.scrollToTourTarget(name)

        if (typeof page.tourTarget !== "function")
            return false

        var target = page.tourTarget(name)
        return scrollPageToItem(page, target)
    }

    function scrollPageToItem(page, target) {
        if (!page || !target)
            return false

        try {
            var flickable = page.contentItem
            if (!flickable || flickable.contentY === undefined)
                return false

            var contentRoot = flickable.contentItem ? flickable.contentItem : flickable
            var point = target.mapToItem(contentRoot, 0, 0)
            var viewHeight = Math.max(1, flickable.height || page.height)
            var contentHeight = Math.max(viewHeight, flickable.contentHeight || page.contentHeight || viewHeight)
            var targetHeight = Math.max(1, target.height || 1)
            var topPadding = Math.min(72, Math.max(28, viewHeight * 0.14))
            var targetTop = Math.max(0, point.y - topPadding)
            var centeredTop = point.y - Math.max(0, (viewHeight - targetHeight) / 2)
            var desiredY = Math.min(targetTop, centeredTop)
            var maxY = Math.max(0, contentHeight - viewHeight)

            flickable.contentY = Math.max(0, Math.min(maxY, desiredY))
            return true
        } catch (e) {
            return false
        }
    }

    function interfaceTourSteps() {
        var ar = backend.language === "ar"
        return [
            {
                pageIndex: 0,
                target: "homeHero",
                titleText: Ui.trx(ar, "مرحبًا بك في BioAuth", "Welcome to BioAuth"),
                bodyText: Ui.trx(ar, "هذه الصفحة تجمع أهم الإجراءات والحالة العامة في مكان واحد.", "This page brings the main actions and overall status into one place.")
            },
            {
                pageIndex: 0,
                target: "homeQuickActions",
                titleText: Ui.trx(ar, "إجراءات سريعة", "Quick actions"),
                bodyText: Ui.trx(ar, "استخدم هذه المنطقة للوصول السريع إلى أكثر المهام شيوعًا بدون الدخول في تفاصيل تقنية.", "Use this area to reach common tasks quickly without technical detail.")
            },
            {
                pageIndex: 0,
                target: "homeStartEnrollment",
                titleText: Ui.trx(ar, "بدء التسجيل", "Start enrollment"),
                bodyText: Ui.trx(ar, "ابدأ جلسات التعلم عندما تكون جاهزًا. الجلسات تساعد BioAuth على بناء النمط السلوكي.", "Start learning sessions when you are ready. Sessions help BioAuth build the behavioral pattern.")
            },
            {
                pageIndex: 0,
                target: "homeLearningProgress",
                titleText: Ui.trx(ar, "تقدم التعلّم", "Learning progress"),
                bodyText: Ui.trx(ar, "هنا ترى ملخصًا بسيطًا عن تقدم التعلم حسب ما يتوفر للنظام.", "Here you see a simple learning-progress summary based on what is available to the system.")
            },
            {
                pageIndex: 0,
                target: "homeTrainModel",
                titleText: Ui.trx(ar, "تدريب نموذج الحماية", "Train protection model"),
                bodyText: Ui.trx(ar, "استخدم هذا الإجراء فقط عندما تشير الواجهة إلى توفر بيانات كافية لتحديث النموذج.", "Use this action only when the interface indicates enough data is available to update the model.")
            },
            {
                pageIndex: 0,
                target: "homeRecentActivity",
                titleText: Ui.trx(ar, "آخر النشاطات", "Recent activity"),
                bodyText: Ui.trx(ar, "يعرض هذا القسم ملخصًا قريبًا للنشاطات المفيدة للمراجعة.", "This section shows a recent summary of useful activity for review.")
            },
            {
                pageIndex: 1,
                target: "protectionHero",
                titleText: Ui.trx(ar, "صفحة الحماية", "Protection page"),
                bodyText: Ui.trx(ar, "الحالة تظهر حسب ما يؤكده النظام، والواجهة تعرض ملخصًا واضحًا وبسيطًا.", "Status appears according to what the system confirms; the interface shows a clear, simple summary.")
            },
            {
                pageIndex: 1,
                target: "protectionFlow",
                titleText: Ui.trx(ar, "تدفق الحماية", "Protection flow"),
                bodyText: Ui.trx(ar, "اتبع هذا القسم لفهم الخطوات العامة بدون تفاصيل معقدة.", "Use this section to understand the general flow without advanced details.")
            },
            {
                pageIndex: 1,
                target: "protectionControl",
                titleText: Ui.trx(ar, "التحكم بالحماية", "Protection controls"),
                bodyText: Ui.trx(ar, "توجد هنا الإجراءات المتاحة حسب الحالة التي يؤكدها النظام حاليًا.", "Available actions appear here according to the state currently confirmed by the system.")
            },
            {
                pageIndex: 5,
                target: "activityHeader",
                titleText: Ui.trx(ar, "سجل النشاط", "Activity history"),
                bodyText: Ui.trx(ar, "راجع من هنا ملخص النشاطات المهمة.", "Review the important activity summary from here.")
            },
            {
                pageIndex: 3,
                target: "faceHero",
                titleText: Ui.trx(ar, "تأكيد الوجه", "Face confirmation"),
                bodyText: Ui.trx(ar, "هذه الصفحة تعرض تجربة تأكيد الوجه من جانب الواجهة فقط، بينما تبقى قرارات الأمان لدى النظام.", "This page shows the interface side of face confirmation; security decisions remain with the system.")
            },
            {
                pageIndex: 2,
                target: "modelUpdateHero",
                titleText: Ui.trx(ar, "تحديث النموذج", "Model update"),
                bodyText: Ui.trx(ar, "هنا تتابع حالة تحديث النموذج كما تعرضها الواجهة، بدون افتراض نجاح أمني غير مؤكد.", "Here you follow model-update status as shown by the interface, without assuming an unconfirmed security result.")
            },
            {
                pageIndex: 2,
                target: "modelSummary",
                titleText: Ui.trx(ar, "ملخص النموذج", "Model summary"),
                bodyText: Ui.trx(ar, "يعرض هذا الكرت خلاصة مفيدة عن النموذج بدون كشف تفاصيل غير ضرورية.", "This card shows a useful model summary without exposing unnecessary details.")
            },
            {
                pageIndex: 2,
                target: "modelTimeline",
                titleText: Ui.trx(ar, "خط زمني للتحديثات", "Update timeline"),
                bodyText: Ui.trx(ar, "تابع هنا تسلسل التحديثات أو الحالات المرتبطة بالنموذج.", "Follow the sequence of updates or model-related states here.")
            },
            {
                pageIndex: 4,
                target: "settingsHero",
                titleText: Ui.trx(ar, "الإعدادات", "Settings"),
                bodyText: Ui.trx(ar, "من هنا يمكنك مراجعة إعدادات التطبيق اليومية.", "From here you can review everyday app settings.")
            }
        ]
    }

    function startInterfaceGuide() {
        if (navDrawer.opened)
            navDrawer.close()
        navSelection = 0
        guidedTour.currentStep = 0
        guidedTour.start()
    }

    function startFirstRunGuide() {
        startInterfaceGuide()
    }

    function refreshInterfaceTourTarget() {
        if (guidedTour && guidedTour.running) {
            shell.scrollToTourTarget(guidedTour.currentTargetName())
            guidedTour.refreshTarget()
        }
    }

    anchors.fill: parent

    ListModel {
        id: userNavModel
        ListElement { navIndex: 0; glyph: "⌂"; titleKey: "user_shell_home"; noteKey: "user_shell_home_note"; tone: "info" }
        ListElement { navIndex: 1; glyph: "◉"; titleKey: "user_shell_protection"; noteKey: "user_shell_protection_note"; tone: "success" }
        ListElement { navIndex: 5; glyph: "▦"; titleKey: "user_shell_activity"; noteKey: "user_shell_activity_note"; tone: "details" }
        ListElement { navIndex: 3; glyph: "☺"; titleKey: "user_shell_face"; noteKey: "user_shell_face_note"; tone: "details" }
        ListElement { navIndex: 2; glyph: "↻"; titleKey: "user_shell_model_update"; noteKey: "user_shell_model_update_note"; tone: "info" }
        ListElement { navIndex: 4; glyph: "⚙"; titleKey: "user_shell_settings"; noteKey: "user_shell_settings_note"; tone: "neutral" }
    }

    Rectangle {
        anchors.fill: parent
        color: theme.surface0 || theme.window

        Rectangle {
            width: parent.width * 0.52
            height: parent.height * 0.6
            x: parent.width * 0.47
            y: -height * 0.32
            radius: width / 2
            color: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, theme.isDark ? 0.07 : 0.12)
            border.color: "transparent"
        }

        Rectangle {
            width: parent.width * 0.38
            height: parent.height * 0.5
            x: -width * 0.28
            y: parent.height * 0.55
            radius: width / 2
            color: Qt.rgba(theme.info.r, theme.info.g, theme.info.b, theme.isDark ? 0.05 : 0.08)
            border.color: "transparent"
        }
    }

    Component {
        id: userNavigationPanelComponent

        ScrollView {
            clip: true
            contentWidth: availableWidth
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            Item {
                width: parent.width
                implicitHeight: userNavigationColumn.implicitHeight + 8

                ColumnLayout {
                    id: userNavigationColumn
                    width: parent.width
                    spacing: shell.denseLayout ? 10 : 14

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        Item {
                            Layout.preferredWidth: shell.denseLayout ? 46 : 54
                            Layout.preferredHeight: shell.denseLayout ? 46 : 54

                            Image {
                                anchors.fill: parent
                                source: shell.brandLogo
                                fillMode: Image.PreserveAspectFit
                                smooth: true
                                mipmap: true
                                asynchronous: true
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2

                            Label {
                                Layout.fillWidth: true
                                text: backend.tr("user_shell_title")
                                color: theme.text
                                font.pixelSize: shell.denseLayout ? 22 : 26
                                font.bold: true
                                elide: Text.ElideRight
                            }

                            Label {
                                Layout.fillWidth: true
                                text: backend.tr("user_shell_subtitle")
                                color: theme.muted
                                font.pixelSize: 12
                                wrapMode: Text.Wrap
                                maximumLineCount: 2
                                elide: Text.ElideRight
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        radius: 20
                        implicitHeight: userCardColumn.implicitHeight + 22
                        color: theme.userCardBg || theme.surface2
                        opacity: 0.96
                        border.color: theme.neutralBorder || theme.border
                        border.width: 1

                        ColumnLayout {
                            id: userCardColumn
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 10

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10

                                Rectangle {
                                    Layout.preferredWidth: shell.denseLayout ? 38 : 40
                                    Layout.preferredHeight: shell.denseLayout ? 38 : 40
                                    radius: width / 2
                                    color: theme.navIconBg || theme.surface2
                                    border.color: theme.neutralBorder || theme.border
                                    border.width: 1

                                    Label {
                                        anchors.centerIn: parent
                                        text: (backend.currentUser.display_name || backend.currentUser.user_id || "B").toString().charAt(0).toUpperCase()
                                        color: theme.text
                                        font.pixelSize: 18
                                        font.bold: true
                                    }
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 3

                                    Label {
                                        Layout.fillWidth: true
                                        text: backend.currentUser.display_name || backend.currentUser.user_id || "BioAuth"
                                        color: theme.text
                                        font.pixelSize: 15
                                        font.bold: true
                                        elide: Text.ElideRight
                                    }

                                    Label {
                                        Layout.fillWidth: true
                                        text: Ui.trx(backend.language === "ar", "الحساب الحالي", "Current account")
                                        color: theme.muted
                                        font.pixelSize: 12
                                        elide: Text.ElideRight
                                    }
                                }
                            }

                            InfoPill {
                                textValue: shell.compactUserStatusText(backend.runtimeState.activeText, Ui.trx(backend.language === "ar", "هادئ", "Idle"))
                                pillTone: backend.runtimeState.active ? (backend.runtimeState.statusTone || "success") : (backend.statusTone || "info")
                            }
                        }
                    }

                    Repeater {
                        model: userNavModel
                        delegate: Rectangle {
                            property bool pointerHover: false

                            Layout.fillWidth: true
                            radius: 18
                            implicitHeight: shell.denseLayout ? 56 : 62
                            color: navSelection === navIndex ? (theme.navActiveBg || theme.surface2)
                                   : pointerHover ? (theme.neutralHover || theme.surface2)
                                   : "transparent"
                            border.color: navSelection === navIndex ? (theme.neutralBorder || theme.border) : "transparent"
                            border.width: 1
                            opacity: enabled ? 1.0 : 0.72

                            Rectangle {
                                width: 3
                                height: parent.height - 20
                                radius: 2
                                anchors.left: parent.left
                                anchors.leftMargin: 8
                                anchors.verticalCenter: parent.verticalCenter
                                color: Ui.roleColor(theme, tone)
                                opacity: navSelection === navIndex ? 0.72 : 0.0
                            }

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 16
                                anchors.rightMargin: 10
                                anchors.topMargin: 9
                                anchors.bottomMargin: 9
                                spacing: 10

                                AssetIcon {
                                    sourceUrl: shell.navIcon(navIndex)
                                    tone: tone
                                    Layout.preferredWidth: shell.denseLayout ? 36 : 38
                                    Layout.preferredHeight: shell.denseLayout ? 36 : 38
                                    iconPadding: 6
                                    showChrome: true
                                    opacity: navSelection === navIndex ? 1.0 : 0.78
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2

                                    Label {
                                        Layout.fillWidth: true
                                        text: shell.navTitle(navIndex, titleKey)
                                        color: theme.text
                                        font.pixelSize: 14
                                        font.bold: true
                                        elide: Text.ElideRight
                                    }

                                    Label {
                                        Layout.fillWidth: true
                                        text: shell.navNote(navIndex, noteKey)
                                        color: theme.muted
                                        font.pixelSize: 11
                                        elide: Text.ElideRight
                                    }
                                }
                            }

                            MouseArea {
                                id: navMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                onEntered: pointerHover = true
                                onExited: pointerHover = false
                                onCanceled: pointerHover = false
                                onClicked: navSelection = navIndex
                                cursorShape: Qt.PointingHandCursor
                            }

                            Behavior on color { ColorAnimation { duration: 120 } }
                            Behavior on border.color { ColorAnimation { duration: 120 } }
                        }
                    }

                    Item { Layout.preferredHeight: 8 }

                    Rectangle {
                        Layout.fillWidth: true
                        implicitHeight: privacyColumn.implicitHeight + 20
                        radius: 20
                        color: theme.surface1
                        opacity: 0.90
                        border.color: theme.neutralBorder || theme.border
                        border.width: 1

                        ColumnLayout {
                            id: privacyColumn
                            anchors.fill: parent
                            anchors.margins: 11
                            spacing: 6

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 8

                                AssetIcon {
                                    sourceUrl: shell.privacyIcon
                                    tone: "success"
                                    Layout.preferredWidth: 34
                                    Layout.preferredHeight: 34
                                    iconPadding: 6
                                }

                                Label {
                                    Layout.fillWidth: true
                                    text: Ui.trx(backend.language === "ar", "بياناتك تبقى محلية", "Your data stays local")
                                    color: theme.text
                                    font.pixelSize: 13
                                    font.bold: true
                                    wrapMode: Text.Wrap
                                }
                            }

                            Label {
                                Layout.fillWidth: true
                                text: Ui.trx(backend.language === "ar", "يعرض BioAuth الحالة المفيدة فقط. تبقى القرارات الحساسة لدى النظام.", "BioAuth shows useful status only. Sensitive decisions stay with the system.")
                                color: theme.muted
                                font.pixelSize: 11
                                wrapMode: Text.Wrap
                            }
                        }
                    }

                    AppButton {
                        Layout.fillWidth: true
                        compact: true
                        text: Ui.trx(backend.language === "ar", "شرح الواجهة", "Guide me")
                        role: "details"
                        onClicked: {
                            if (navDrawer.opened)
                                navDrawer.close()
                            shell.startInterfaceGuide()
                        }
                    }

                    AppButton {
                        Layout.fillWidth: true
                        compact: true
                        text: backend.tr("logout")
                        role: "neutral"
                        onClicked: backend.logout()
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
            color: theme.surface3 || theme.surface2
            border.color: theme.border
        }

        Loader {
            anchors.fill: parent
            anchors.margins: 14
            active: shell.sidebarAsDrawer
            asynchronous: true
            sourceComponent: userNavigationPanelComponent
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: shell.sidebarAsDrawer ? 12 : (compactLayout ? 18 : 26)
        spacing: shell.sidebarAsDrawer ? 12 : (compactLayout ? 16 : 24)

        GlassCard {
            visible: !shell.sidebarAsDrawer
            Layout.preferredWidth: shell.sidebarAsDrawer ? 0 : shell.sidebarWidth
            Layout.minimumWidth: shell.sidebarAsDrawer ? 0 : Math.max(188, shell.sidebarWidth - 18)
            Layout.maximumWidth: shell.sidebarAsDrawer ? 0 : shell.sidebarWidth
            Layout.fillHeight: true

            Loader {
                anchors.fill: parent
                anchors.margins: denseLayout ? 14 : 18
                active: !shell.sidebarAsDrawer
                asynchronous: true
                sourceComponent: userNavigationPanelComponent
            }
        }

        GlassCard {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: shell.sidebarAsDrawer ? 14 : (denseLayout ? 16 : 24)
                spacing: denseLayout ? 14 : 18

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 14

                    AppButton {
                        visible: shell.sidebarAsDrawer
                        text: Ui.trx(backend.language === "ar", "القائمة", "Menu")
                        role: "details"
                        compact: true
                        onClicked: navDrawer.open()
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4

                        Label {
                            Layout.fillWidth: true
                            text: shell.navTitle(navSelection, shell.pageTitleKey(navSelection))
                            color: theme.text
                            font.pixelSize: shell.sidebarAsDrawer ? 22 : (denseLayout ? 24 : 30)
                            font.bold: true
                            elide: Text.ElideRight
                        }

                        Label {
                            Layout.fillWidth: true
                            text: shell.navNote(navSelection, shell.pageNoteKey(navSelection))
                            color: theme.muted
                            font.pixelSize: shell.sidebarAsDrawer ? 12 : 13
                            wrapMode: Text.Wrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                        }
                    }

                    InfoPill {
                        visible: !shell.sidebarAsDrawer || shell.width > 760
                        textValue: shell.userSafeStatusText(backend.runtimeState.activeText, backend.tr("status_idle"))
                        pillTone: backend.runtimeState.active ? (backend.runtimeState.statusTone || "success") : (backend.statusTone || "info")
                    }
                }

                InfoPill {
                    visible: shell.sidebarAsDrawer && shell.width <= 760
                    Layout.alignment: Qt.AlignLeft
                    textValue: shell.userSafeStatusText(backend.runtimeState.activeText, backend.tr("status_idle"))
                    pillTone: backend.runtimeState.active ? (backend.runtimeState.statusTone || "success") : (backend.statusTone || "info")
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
                            id: userHomeLoader
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            active: navSelection === 0
                            asynchronous: true
                            sourceComponent: userHomePageComponent
                            onLoaded: shell.refreshInterfaceTourTarget()
                        }

                        Loader {
                            id: userProtectionLoader
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            active: navSelection === 1
                            asynchronous: true
                            sourceComponent: userProtectionPageComponent
                            onLoaded: shell.refreshInterfaceTourTarget()
                        }

                        Loader {
                            id: userModelUpdateLoader
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            active: navSelection === 2
                            asynchronous: true
                            sourceComponent: userModelUpdatePageComponent
                            onLoaded: shell.refreshInterfaceTourTarget()
                        }

                        Loader {
                            id: userFaceLoader
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            active: navSelection === 3
                            asynchronous: true
                            sourceComponent: userFaceConfirmationPageComponent
                            onLoaded: shell.refreshInterfaceTourTarget()
                        }

                        Loader {
                            id: userSettingsLoader
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            active: navSelection === 4
                            asynchronous: true
                            sourceComponent: userSettingsPageComponent
                            onLoaded: shell.refreshInterfaceTourTarget()
                        }

                        Loader {
                            id: userActivityLoader
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            active: navSelection === 5
                            asynchronous: true
                            sourceComponent: userActivityPageComponent
                            onLoaded: shell.refreshInterfaceTourTarget()
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
            }

            Component { id: userHomePageComponent; UserHomePage { rootWindow: shell } }
            Component { id: userProtectionPageComponent; UserProtectionPage { rootWindow: shell } }
            Component { id: userModelUpdatePageComponent; UserModelUpdatePage { rootWindow: shell } }
            Component { id: userFaceConfirmationPageComponent; UserFaceConfirmationPage { rootWindow: shell } }
            Component { id: userSettingsPageComponent; UserSettingsPage { rootWindow: shell } }
            Component { id: userActivityPageComponent; UserActivityPage { rootWindow: shell } }
        }
    }

    GuidedTourOverlay {
        id: guidedTour
        anchors.fill: parent
        z: 9999
        theme: shell.theme
        controller: shell
        steps: shell.interfaceTourSteps()
        onPageRequested: function(pageIndex) {
            if (navDrawer.opened)
                navDrawer.close()
            if (pageIndex === 0 || pageIndex === 1 || pageIndex === 2 ||
                    pageIndex === 3 || pageIndex === 4 || pageIndex === 5)
                shell.navSelection = pageIndex
        }
        onCompleted: function(skipped) {
            // Required backend contract for persistent per-user interface tour state:
            // - property bool interfaceTourPending
            // - property bool interfaceTourCompleted
            // - signal interfaceTourChanged()
            // - method markInterfaceTourCompleted(skipped)
            // - method resetInterfaceTour()
            // Phase 5 is UI-only, so completion stays local to GuidedTourOverlay.
        }
    }
}
