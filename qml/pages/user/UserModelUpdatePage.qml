import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"
import "../../theme/Ui.js" as Ui

ScrollView {
    id: root
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property bool approvalActionInFlight: false
    readonly property bool denseLayout: width < 980
    readonly property var approval: backend.productionApprovalState || ({})
    readonly property var modelState: backend.modelReadinessState || ({})
    readonly property bool pendingApproval: approval.productionReadyPendingUserApproval === true || approval.production_ready_pending_user_approval === true
    readonly property bool canApproveModelSwitch: pendingApproval && !approvalActionInFlight
    readonly property url heroImage: Qt.resolvedUrl("../../assets/bioauth/01_hero_integrated/01_protection_update_arrow_integrated.png")
    readonly property url updateIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/29_download_update.png")
    readonly property url currentIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/28_verification_shield.png")
    readonly property url reviewIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/36_apply_target.png")
    readonly property url shieldIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/02_protection_shield.png")
    readonly property url infoIcon: Qt.resolvedUrl("../../assets/bioauth/user_icons/22_info.png")

    clip: true
    contentWidth: availableWidth

    Timer {
        id: approvalGuardTimer
        interval: 1500
        repeat: false
        onTriggered: root.approvalActionInFlight = false
    }

    Connections {
        target: backend
        function onModelReadinessChanged() { root.approvalActionInFlight = false }
        function onProfileChanged() { root.approvalActionInFlight = false }
        function onStatusChanged() { root.approvalActionInFlight = false }
    }

    function label(arText, enText) {
        return Ui.trx(backend.language === "ar", arText, enText)
    }

    function tourTarget(name) {
        if (name === "modelUpdateHero") return modelUpdateHeroCard
        if (name === "modelSummary") return modelSummaryCard
        if (name === "modelTimeline") return modelTimelineCard
        return null
    }

    function userSafeText(value, fallbackText) {
        var text = String(value || "")
        if (text.length === 0)
            return fallbackText || ""
        var lower = text.toLowerCase()
        if (lower.indexOf("sha" + "dow") >= 0 || lower.indexOf("candidate") >= 0 || lower.indexOf("challenger") >= 0 || lower.indexOf("promotion") >= 0 || lower.indexOf("ledger") >= 0 || lower.indexOf("digest") >= 0) {
            if (lower.indexOf("suspicious") >= 0 || lower.indexOf("attention") >= 0 || lower.indexOf("fail") >= 0 || lower.indexOf("mismatch") >= 0)
                return root.label("مراجعة تحديث الحماية تحتاج انتباهًا", "Protection update review needs attention")
            if (lower.indexOf("pending") >= 0 || lower.indexOf("waiting") >= 0 || lower.indexOf("partial") >= 0 || lower.indexOf("collecting") >= 0)
                return root.label("يتم جمع أدلة آمنة قبل إتاحة التحديث.", "Safe evidence is being collected before the update becomes available.")
            return root.label("تحديث الحماية قيد المراجعة في الخلفية.", "A protection update is being reviewed in the background.")
        }
        if (lower.indexOf("model") >= 0 && lower.indexOf("file") >= 0 && lower.indexOf("missing") >= 0)
            return root.label("إعداد النموذج غير مكتمل", "Model setup is incomplete")
        if (lower.indexOf("production") >= 0 || lower.indexOf("runtime") >= 0 || lower.indexOf("approval") >= 0 || lower.indexOf("gate") >= 0)
            return root.label("يتم التأكد من جاهزية التحديث قبل عرضه للتطبيق.", "BioAuth is checking update readiness before it can be applied.")
        return text
    }

    function reviewHeroTitle() {
        if (root.pendingApproval)
            return root.label("تحديث حماية جاهز للمراجعة", "Protection update ready for review")
        return root.label("لا يوجد تحديث حماية متاح الآن", "No protection update is available right now")
    }

    function reviewHeroBody() {
        if (root.pendingApproval)
            return root.label("راجع التحديث ثم طبّقه فقط إذا كنت جاهزًا. يبقى نموذج الحماية الحالي نشطًا حتى تؤكد BioAuth التفعيل.", "Review the update and apply it only when you are ready. The current protection model stays active until BioAuth confirms activation.")
        return root.userSafeText(modelState.safeUserMessage, root.label("سيظهر هنا أي تحديث جديد عندما يصبح جاهزًا للمراجعة. لا يتم تطبيق أي تحديث بصمت.", "A new update will appear here when it is ready for review. No update is applied silently."))
    }

    function reviewStatusText() {
        if (root.pendingApproval)
            return root.label("بانتظار قرارك", "Waiting for your decision")
        return root.label("لا إجراء مطلوب", "No action needed")
    }

    function approvePendingModelSwitch() {
        if (!root.canApproveModelSwitch)
            return
        root.approvalActionInFlight = true
        approvalGuardTimer.restart()
        backend.requestUserApproveModelUpdate()
    }

    ColumnLayout {
        width: root.availableWidth
        spacing: 18

        GlassCard {
            id: modelUpdateHeroCard
            Layout.fillWidth: true
            implicitHeight: Math.max(root.denseLayout ? 500 : 410, modelUpdateHeroContent.implicitHeight + (root.denseLayout ? 32 : 44))
            Layout.minimumHeight: implicitHeight

            RowLayout {
                id: modelUpdateHeroContent
                anchors.fill: parent
                anchors.margins: root.denseLayout ? 16 : 22
                spacing: root.denseLayout ? 14 : 22

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: root.denseLayout ? modelUpdateHeroCard.width : modelUpdateHeroCard.width * 0.60
                    Layout.maximumWidth: root.denseLayout ? modelUpdateHeroCard.width : modelUpdateHeroCard.width * 0.62
                    spacing: 14

                    InfoPill {
                        textValue: root.pendingApproval ? root.label("تحديث متاح", "Update available") : root.label("لا يوجد تحديث الآن", "No update now")
                        pillTone: root.pendingApproval ? "success" : "info"
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.reviewHeroTitle()
                        color: theme.text
                        font.pixelSize: root.denseLayout ? 28 : 34
                        font.bold: true
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.reviewHeroBody()
                        color: theme.muted
                        font.pixelSize: 15
                        wrapMode: Text.Wrap
                        lineHeight: 1.12
                        maximumLineCount: 3
                        elide: Text.ElideRight
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: root.width < 620 ? 1 : 2
                        columnSpacing: 12
                        rowSpacing: 10

                        AppButton {
                            Layout.preferredWidth: 160
                            Layout.fillWidth: root.width < 620
                            text: approvalActionInFlight ? backend.tr("user_action_working") : root.label("مراجعة وتطبيق", "Review and apply")
                            role: root.pendingApproval ? "primary" : "neutral"
                            enabled: root.canApproveModelSwitch
                            ToolTip.visible: hovered && !enabled
                            ToolTip.text: approvalActionInFlight ? backend.tr("user_action_in_progress") : backend.tr("user_model_update_unavailable_tooltip")
                            onClicked: root.approvePendingModelSwitch()
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: approvalActionInFlight ? backend.tr("user_action_in_progress") : root.userSafeText(backend.statusMessage, backend.tr("user_model_update_status_hint"))
                        color: approvalActionInFlight ? theme.accent : theme.muted
                        font.pixelSize: 13
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                    }
                }

                HeroAssetFrame {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.preferredWidth: modelUpdateHeroCard.width * 0.38
                    visible: !root.denseLayout
                    sourceUrl: root.heroImage
                    tone: root.pendingApproval ? "success" : "info"
                    cornerRadius: 26
                    imageBleed: 8
                    imageFillMode: Image.PreserveAspectCrop
                    imageOpacity: 1.0
                    overlayOpacity: 0.0
                    edgeFadeOpacity: 0.0
                    ambientWashOpacity: 0.0
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: root.denseLayout ? 1 : 2
            columnSpacing: 18
            rowSpacing: 18

            PremiumMetricCard {
                Layout.fillWidth: true
                Layout.minimumHeight: 118
                compact: true
                iconSource: root.currentIcon
                tone: "info"
                title: root.label("الحماية الحالية", "Current protection")
                value: root.label("النموذج الحالي نشط", "Current model active")
                detail: root.label("يبقى هو المسؤول عن الحماية حتى يتم تطبيق تحديث مؤكد.", "It remains responsible for protection until a confirmed update is applied.")
            }

            PremiumMetricCard {
                Layout.fillWidth: true
                Layout.minimumHeight: 118
                compact: true
                iconSource: root.updateIcon
                tone: root.pendingApproval ? "success" : "info"
                title: root.label("التحديث الجديد", "New update")
                value: root.reviewStatusText()
                detail: root.pendingApproval ? root.label("التحديث مؤهل للمراجعة اليدوية قبل التطبيق.", "The update is eligible for manual review before applying.") : root.label("لا يوجد تحديث متاح حاليًا.", "No update is available right now.")
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: root.denseLayout ? 1 : 2
            columnSpacing: 18
            rowSpacing: 18

            GlassCard {
                id: modelSummaryCard
                Layout.fillWidth: true
                implicitHeight: modelSummaryContent.implicitHeight + 36
                Layout.minimumHeight: implicitHeight

                ColumnLayout {
                    id: modelSummaryContent
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 12

                    Label {
                        Layout.fillWidth: true
                        text: root.label("ملخص التحديث", "Update summary")
                        color: theme.text
                        font.pixelSize: 22
                        font.bold: true
                        wrapMode: Text.Wrap
                    }

                    StatusInfoRow {
                        Layout.fillWidth: true
                        iconSource: root.shieldIcon
                        tone: "success"
                        title: root.label("تحسين الحماية", "Protection improvement")
                        detail: root.label("يعرض BioAuth فقط معلومات آمنة ومفهومة عن التحديث، بدون تفاصيل داخلية.", "BioAuth shows only safe, understandable update information without internal details.")
                    }

                    StatusInfoRow {
                        Layout.fillWidth: true
                        iconSource: root.infoIcon
                        tone: "info"
                        title: root.label("جاهزية التحديث", "Update readiness")
                        detail: root.userSafeText(modelState.safeUserMessage, backend.tr("user_model_update_status_hint"))
                    }

                    StatusInfoRow {
                        Layout.fillWidth: true
                        iconSource: root.reviewIcon
                        tone: root.pendingApproval ? "success" : "neutral"
                        title: root.label("قرارك", "Your decision")
                        detail: root.pendingApproval ? root.label("التطبيق لا يفعّل التحديث بدون إجراء واضح منك.", "The app does not apply the update without a clear action from you.") : root.label("لا يظهر نجاح أو تفعيل قبل أن يؤكده التطبيق.", "No success or activation is shown before the app confirms it.")
                    }
                }
            }

            GlassCard {
                id: modelTimelineCard
                Layout.fillWidth: true
                implicitHeight: modelTimelineContent.implicitHeight + 36
                Layout.minimumHeight: implicitHeight

                ColumnLayout {
                    id: modelTimelineContent
                    anchors.fill: parent
                    anchors.margins: 18
                    spacing: 12

                    Label {
                        Layout.fillWidth: true
                        text: root.label("مسار التحديث", "Update timeline")
                        color: theme.text
                        font.pixelSize: 22
                        font.bold: true
                        wrapMode: Text.Wrap
                    }

                    StoryboardStep {
                        Layout.fillWidth: true
                        stepNumber: 1
                        title: root.label("مراجعة آمنة", "Safe review")
                        detail: root.pendingApproval ? root.label("يوجد تحديث مؤهل للمراجعة، لكنه لا يؤثر على الحماية الحالية قبل تطبيقه.", "An update is eligible for review, but it does not affect current protection before applying.") : root.label("لا يوجد تحديث مؤهل حاليًا.", "No eligible update right now.")
                        stateText: root.pendingApproval ? root.label("متاح", "Available") : root.label("بانتظار", "Waiting")
                        tone: root.pendingApproval ? "success" : "neutral"
                        active: root.pendingApproval
                    }

                    StoryboardStep {
                        Layout.fillWidth: true
                        stepNumber: 2
                        title: root.label("مراجعة القرار", "Decision review")
                        detail: root.label("لا يتم التطبيق تلقائيًا؛ القرار يبقى بإجراء صريح.", "Applying is never automatic; it requires explicit action.")
                        stateText: root.canApproveModelSwitch ? root.label("جاهز", "Ready") : root.label("غير متاح", "Unavailable")
                        tone: root.canApproveModelSwitch ? "success" : "neutral"
                        active: root.canApproveModelSwitch
                    }

                    StoryboardStep {
                        Layout.fillWidth: true
                        stepNumber: 3
                        title: root.label("التطبيق", "Apply")
                        detail: root.label("بعد تطبيق التحديث، يؤكد BioAuth الحالة قبل عرض أي نجاح.", "After applying the update, BioAuth confirms the state before showing success.")
                        stateText: root.label("بعد الموافقة", "After approval")
                        tone: "info"
                    }
                }
            }
        }
    }
}
