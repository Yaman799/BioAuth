import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "../components"

Item {
    id: root
    objectName: "hybridDirectTestPage"
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property bool compactLayout: rootWindow ? rootWindow.compactLayout : width < 1180
    readonly property var hybridState: backend.hybridDirectState || ({})
    readonly property var safetyGates: hybridState.safety_gate_results || ({})
    readonly property var classicRisk: hybridState.classic_risk || ({})
    readonly property var keyboardRisk: hybridState.keyboard_risk || ({})
    readonly property var mouseRisk: hybridState.mouse_risk || ({})
    readonly property var combinedRisk: hybridState.combined_risk || ({})
    readonly property var latestResult: backend.latestHybridDirectTestResult || ({})
    readonly property var latestLiveSessionEvalResult: backend.latestHybridLiveSessionEvalResult || ({})
    readonly property var latestLiveSessionEvalReportState: backend.latestHybridLiveSessionEvalReportState || ({})
    readonly property var liveCandidateObserverState: backend.liveCandidateObserverState || ({})
    readonly property var candidateGroups: backend.hybridDirectCandidateGroups || []
    readonly property var groupVotes: backend.hybridDirectGroupVotes || []
    readonly property var latestReportState: backend.latestHybridDirectReportState || ({})
    readonly property var hybridProStatus: hybridState.hybridProStatus || ({})
    readonly property var hybridLayerReadiness: hybridState.hybridProLayerReadiness || ({})
    readonly property var hybridLayerReadinessLayers: hybridLayerReadiness.layers || ({})
    readonly property var hybridModalityMapping: hybridLayerReadiness.modality_mapping || ({})
    readonly property bool denseWindow: (Window.width || 0) > 0 && Window.width < 980

    function trx(arText, enText) { return rootWindow ? rootWindow.trx(arText, enText) : enText }
    function valueOrUnavailable(value) { return value === undefined || value === null || value === "" ? root.trx("غير متاح", "Unavailable") : String(value) }
    function boolLabel(value) { return value === true ? root.trx("نعم", "Yes") : (value === false ? root.trx("لا", "No") : root.trx("غير متاح", "Unavailable")) }
    function numberOrUnavailable(value) {
        if (value === undefined || value === null || value === "") return root.trx("غير متاح", "Unavailable")
        var parsed = Number(value)
        return isNaN(parsed) ? String(value) : parsed.toFixed(parsed >= 100 ? 0 : 3)
    }
    function listText(value) {
        if (value === undefined || value === null) return root.trx("لا يوجد", "None")
        if (Array.isArray(value)) return value.length > 0 ? value.join(", ") : root.trx("لا يوجد", "None")
        var text = String(value)
        return text.length > 0 ? text : root.trx("لا يوجد", "None")
    }
    function riskValue(payload, key) {
        return payload && payload[key] !== undefined && payload[key] !== null && payload[key] !== "" ? payload[key] : root.trx("غير متاح", "Unavailable")
    }
    function gateValue(gateName, key) {
        var gate = safetyGates[gateName] || ({})
        return gate[key] !== undefined && gate[key] !== null && gate[key] !== "" ? gate[key] : root.trx("غير متاح", "Unavailable")
    }
    function gateCodes(gateName) {
        var gate = safetyGates[gateName] || ({})
        return root.listText(gate.reason_codes)
    }
    function layerPayload(layerName) {
        return hybridLayerReadinessLayers[layerName] || ({})
    }
    function layerWindowText(layerName) {
        var layer = root.layerPayload(layerName)
        return root.valueOrUnavailable(layer.positive_windows) + "/" + root.valueOrUnavailable(layer.required_positive_windows)
    }
    function layerBackendSummaryText(layerName) {
        var layer = root.layerPayload(layerName)
        return root.trx("ready", "ready") + "=" + root.boolLabel(layer.ready)
               + ", " + root.trx("gap", "gap") + "=" + root.valueOrUnavailable(layer.gap)
               + ", " + root.trx("reasons", "reasons") + "=" + root.listText(layer.reason_codes)
    }
    function mappingFieldsText(fieldName) {
        var key = fieldName + "_source_fields"
        return root.listText(root.hybridModalityMapping[key])
    }
    function displayValue(value) { return root.numberOrUnavailable(value) }
    function rowValue(payload, key) {
        if (!payload) return root.trx("غير متاح", "Unavailable")
        return root.valueOrUnavailable(payload[key])
    }
    function lowerText(value) { return String(value === undefined || value === null ? "" : value).toLowerCase() }
    function statusTone(value) {
        var v = root.lowerText(value)
        if (v === "available" || v === "completed" || v === "ready" || v === "ok") return "success"
        if (v.indexOf("fail") >= 0 || v.indexOf("error") >= 0) return "danger"
        if (v === "unavailable" || v === "skipped" || v === "missing") return "warn"
        return "details"
    }
    function decisionTone(value) {
        var v = root.lowerText(value)
        if (v === "intruder" || v === "reject" || v === "rejected" || v === "blocked") return "danger"
        if (v === "genuine" || v === "owner" || v === "legit" || v === "authorized") return "success"
        if (v === "abstain" || v === "unavailable") return "warn"
        return "details"
    }
    function artifactTone(value) {
        var v = root.lowerText(value)
        if (v === "available" || v === "loaded" || v === "true" || v === "yes") return "success"
        if (v.indexOf("missing") >= 0 || v === "unavailable" || v === "false" || v === "no") return "warn"
        return "details"
    }
    function pairText(left, right) { return root.displayValue(left) + " / " + root.displayValue(right) }

    ScrollView {
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        ColumnLayout {
            width: parent.width
            spacing: root.compactLayout ? 14 : 18

            GlassCard {
                objectName: "hybridDirectOverviewCard"
                Layout.fillWidth: true
                implicitHeight: overviewColumn.implicitHeight + 32

                ColumnLayout {
                    id: overviewColumn
                    anchors.fill: parent
                    anchors.margins: root.compactLayout ? 16 : 22
                    spacing: 14

                    SectionHeader {
                        title: root.trx("Hybrid Direct Test", "Hybrid Direct Test")
                        subtitle: root.trx(
                            "صفحة عرض وتحكم مملوكة للباكند. Run Hybrid Direct Test هو تقييم test/replay/offline ولا يفعّل Direct Live Control.",
                            "Backend-driven display and control surface. Run Hybrid Direct Test is a test/replay/offline evaluation action and does not enable Direct Live Control."
                        )
                        Layout.fillWidth: true
                    }

                    Label {
                        objectName: "hybridDirectOffByDefaultNotice"
                        text: root.trx(
                            "Direct Live Control يبقى OFF افتراضيًا ومنفصلًا عن Run Hybrid Direct Test. لا يوجد مودل منفرد يستطيع قفل الجهاز، وأي تأثير على الجهاز معطل في هذا العقد.",
                            "Direct Live Control remains OFF by default and separate from Run Hybrid Direct Test. No single model can lock the device, and device influence is disabled in this contract."
                        )
                        color: theme.text
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: root.compactLayout ? 1 : 3
                        columnSpacing: 12
                        rowSpacing: 12

                        StatTile {
                            objectName: "hybridDirectEnabledTile"
                            Layout.fillWidth: true
                            title: root.trx("Direct control", "Direct control")
                            value: root.boolLabel(hybridState.enabled)
                            subtitle: root.trx("قيمة backend.hybridDirectState.enabled", "Value from backend.hybridDirectState.enabled")
                            accentColor: hybridState.enabled === true ? theme.warn : theme.success
                            badge: root.valueOrUnavailable(hybridState.mode)
                        }

                        StatTile {
                            objectName: "hybridDirectInfluenceTile"
                            Layout.fillWidth: true
                            title: root.trx("Can influence device", "Can influence device")
                            value: root.boolLabel(hybridState.can_influence_device)
                            subtitle: root.trx("يجب أن تبقى معطلة حتى مراحل safety gates اللاحقة", "Must remain disabled until later safety-gated phases")
                            accentColor: hybridState.can_influence_device === true ? theme.danger : theme.success
                            badge: root.trx("Backend", "Backend")
                        }

                        StatTile {
                            objectName: "hybridDirectFinalActionTile"
                            Layout.fillWidth: true
                            title: root.trx("Final action", "Final action")
                            value: root.valueOrUnavailable(hybridState.final_action)
                            subtitle: root.valueOrUnavailable(hybridState.final_action_provenance)
                            accentColor: theme.info
                            badge: root.trx("Provenance", "Provenance")
                        }
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 10
                        InfoPill { objectName: "hybridDirectNoSingleModelPill"; textValue: root.trx("No single model can lock", "No single model can lock") + ": " + root.boolLabel(hybridState.no_single_model_can_lock); pillTone: "success" }
                        InfoPill { textValue: root.trx("Experiment can lock alone", "Experiment can lock alone") + ": " + root.boolLabel(hybridState.experiment_can_lock_alone); pillTone: hybridState.experiment_can_lock_alone === true ? "danger" : "success" }
                        InfoPill { textValue: root.trx("Face required", "Face required") + ": " + root.boolLabel(hybridState.face_required); pillTone: "details" }
                        InfoPill { textValue: root.trx("Timestamp", "Timestamp") + ": " + root.valueOrUnavailable(hybridState.timestamp); pillTone: "details" }
                    }
                }
            }

            GlassCard {
                objectName: "hybridProCapabilityCard"
                Layout.fillWidth: true
                implicitHeight: hybridProCapabilityColumn.implicitHeight + 32

                ColumnLayout {
                    id: hybridProCapabilityColumn
                    anchors.fill: parent
                    anchors.margins: root.compactLayout ? 16 : 22
                    spacing: 12

                    SectionHeader {
                        title: root.trx("Hybrid Pro capability", "Hybrid Pro capability")
                        subtitle: root.trx(
                            "هذه الحالة من الباكند: تميّز بين المكتبات المثبتة، artifacts المدربة، ووضع runtime الحالي.",
                            "Backend-owned status: distinguishes installed libraries, trained artifacts, and current runtime mode."
                        )
                        Layout.fillWidth: true
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 10
                        InfoPill { objectName: "hybridProLibrariesPill"; textValue: root.trx("Libraries", "Libraries") + ": " + root.boolLabel(hybridState.hybridProLibrariesAvailable); pillTone: hybridState.hybridProLibrariesAvailable === true ? "success" : "warn" }
                        InfoPill { objectName: "hybridProArtifactsPill"; textValue: root.trx("Artifacts", "Artifacts") + ": " + root.boolLabel(hybridState.hybridProArtifactsAvailable); pillTone: hybridState.hybridProArtifactsAvailable === true ? "success" : "warn" }
                        InfoPill { objectName: "hybridRuntimeModePill"; textValue: root.trx("Runtime mode", "Runtime mode") + ": " + root.valueOrUnavailable(hybridState.hybridRuntimeMode); pillTone: "details" }
                        InfoPill { objectName: "hybridRuntimeFamilyPill"; textValue: root.trx("Model family", "Model family") + ": " + root.valueOrUnavailable(hybridState.hybridRuntimeModelFamily); pillTone: "details" }
                    }

                    Label {
                        objectName: "hybridProStatusLabel"
                        text: root.trx("Hybrid Pro status", "Hybrid Pro status") + ": " + root.valueOrUnavailable(hybridState.hybridProStatusLabel)
                        color: theme.text
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Label {
                        objectName: "hybridProMissingArtifactsLabel"
                        text: root.trx("Missing artifacts", "Missing artifacts") + ": " + root.listText(hybridState.hybridProMissingArtifacts)
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Label {
                        objectName: "hybridProReasonCodesLabel"
                        text: root.trx("Hybrid Pro reason codes", "Hybrid Pro reason codes") + ": " + root.listText(hybridState.hybridProReasonCodes)
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Flow {
                        objectName: "hybridProLayerReadinessFlow"
                        Layout.fillWidth: true
                        spacing: 10
                        InfoPill { objectName: "keyboardReadinessPill"; textValue: root.trx("Keyboard windows", "Keyboard windows") + ": " + root.layerWindowText("keyboard"); pillTone: root.layerPayload("keyboard").ready === true ? "success" : "warn" }
                        InfoPill { objectName: "mouseReadinessPill"; textValue: root.trx("Mouse windows", "Mouse windows") + ": " + root.layerWindowText("mouse"); pillTone: root.layerPayload("mouse").ready === true ? "success" : "warn" }
                        InfoPill { objectName: "combinedReadinessPill"; textValue: root.trx("Combined windows", "Combined windows") + ": " + root.layerWindowText("combined"); pillTone: root.layerPayload("combined").ready === true ? "success" : "warn" }
                    }
                    Label {
                        objectName: "hybridProLayerReadinessSummaryLabel"
                        text: root.trx("Layer readiness", "Layer readiness") + ": "
                              + root.trx("Keyboard", "Keyboard") + " " + root.layerBackendSummaryText("keyboard") + "; "
                              + root.trx("Mouse", "Mouse") + " " + root.layerBackendSummaryText("mouse") + "; "
                              + root.trx("Combined", "Combined") + " " + root.layerBackendSummaryText("combined")
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Label {
                        objectName: "hybridProModalityMappingLabel"
                        text: root.trx("Modality fields", "Modality fields") + ": "
                              + root.trx("Keyboard", "Keyboard") + "=" + root.mappingFieldsText("keyboard") + "; "
                              + root.trx("Mouse", "Mouse") + "=" + root.mappingFieldsText("mouse")
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                }
            }

            GridLayout {
                objectName: "hybridDirectModelGrid"
                Layout.fillWidth: true
                columns: root.compactLayout ? 1 : 2
                columnSpacing: 14
                rowSpacing: 14

                GlassCard {
                    objectName: "hybridDirectClassicLayerCard"
                    Layout.fillWidth: true
                    implicitHeight: classicColumn.implicitHeight + 32
                    ColumnLayout {
                        id: classicColumn
                        anchors.fill: parent
                        anchors.margins: root.compactLayout ? 16 : 22
                        spacing: 10
                        SectionHeader { title: root.trx("Classic Layer", "Classic Layer"); subtitle: root.trx("حالة classic_risk من الباكند", "Backend classic_risk payload"); Layout.fillWidth: true }
                        Flow { Layout.fillWidth: true; spacing: 10
                            InfoPill { textValue: root.trx("Status", "Status") + ": " + root.valueOrUnavailable(root.riskValue(classicRisk, "status")); pillTone: "details" }
                            InfoPill { textValue: root.trx("Decision", "Decision") + ": " + root.valueOrUnavailable(root.riskValue(classicRisk, "decision")); pillTone: "details" }
                            InfoPill { textValue: root.trx("Risk", "Risk") + ": " + root.numberOrUnavailable(root.riskValue(classicRisk, "risk")); pillTone: "details" }
                            InfoPill { textValue: root.trx("Can lock", "Can lock") + ": " + root.boolLabel(classicRisk.can_lock); pillTone: "success" }
                        }
                        Label { text: root.trx("Reason codes", "Reason codes") + ": " + root.listText(classicRisk.reason_codes); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }

                GlassCard {
                    objectName: "hybridDirectKeyboardVerifierCard"
                    Layout.fillWidth: true
                    implicitHeight: keyboardColumn.implicitHeight + 32
                    ColumnLayout {
                        id: keyboardColumn
                        anchors.fill: parent
                        anchors.margins: root.compactLayout ? 16 : 22
                        spacing: 10
                        SectionHeader { title: root.trx("Keyboard Verifier", "Keyboard Verifier"); subtitle: root.trx("حالة keyboard_risk من الباكند", "Backend keyboard_risk payload"); Layout.fillWidth: true }
                        Flow { Layout.fillWidth: true; spacing: 10
                            InfoPill { textValue: root.trx("Status", "Status") + ": " + root.valueOrUnavailable(root.riskValue(keyboardRisk, "status")); pillTone: "details" }
                            InfoPill { textValue: root.trx("Decision", "Decision") + ": " + root.valueOrUnavailable(root.riskValue(keyboardRisk, "decision")); pillTone: "details" }
                            InfoPill { textValue: root.trx("Risk", "Risk") + ": " + root.numberOrUnavailable(root.riskValue(keyboardRisk, "risk")); pillTone: "details" }
                            InfoPill { textValue: root.trx("Can lock", "Can lock") + ": " + root.boolLabel(keyboardRisk.can_lock); pillTone: "success" }
                        }
                        Label { text: root.trx("Reason codes", "Reason codes") + ": " + root.listText(keyboardRisk.reason_codes); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }

                GlassCard {
                    objectName: "hybridDirectMouseVerifierCard"
                    Layout.fillWidth: true
                    implicitHeight: mouseColumn.implicitHeight + 32
                    ColumnLayout {
                        id: mouseColumn
                        anchors.fill: parent
                        anchors.margins: root.compactLayout ? 16 : 22
                        spacing: 10
                        SectionHeader { title: root.trx("Mouse Verifier", "Mouse Verifier"); subtitle: root.trx("حالة mouse_risk من الباكند", "Backend mouse_risk payload"); Layout.fillWidth: true }
                        Flow { Layout.fillWidth: true; spacing: 10
                            InfoPill { textValue: root.trx("Status", "Status") + ": " + root.valueOrUnavailable(root.riskValue(mouseRisk, "status")); pillTone: "details" }
                            InfoPill { textValue: root.trx("Decision", "Decision") + ": " + root.valueOrUnavailable(root.riskValue(mouseRisk, "decision")); pillTone: "details" }
                            InfoPill { textValue: root.trx("Risk", "Risk") + ": " + root.numberOrUnavailable(root.riskValue(mouseRisk, "risk")); pillTone: "details" }
                            InfoPill { textValue: root.trx("Can lock", "Can lock") + ": " + root.boolLabel(mouseRisk.can_lock); pillTone: "success" }
                        }
                        Label { text: root.trx("Reason codes", "Reason codes") + ": " + root.listText(mouseRisk.reason_codes); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }

                GlassCard {
                    objectName: "hybridDirectCombinedVerifierCard"
                    Layout.fillWidth: true
                    implicitHeight: combinedColumn.implicitHeight + 32
                    ColumnLayout {
                        id: combinedColumn
                        anchors.fill: parent
                        anchors.margins: root.compactLayout ? 16 : 22
                        spacing: 10
                        SectionHeader { title: root.valueOrUnavailable(combinedRisk.display_label); subtitle: root.trx("حالة combined_risk من الباكند", "Backend combined_risk payload"); Layout.fillWidth: true }
                        Flow { Layout.fillWidth: true; spacing: 10
                            InfoPill { textValue: root.trx("Status", "Status") + ": " + root.valueOrUnavailable(root.riskValue(combinedRisk, "status")); pillTone: "details" }
                            InfoPill { textValue: root.trx("Decision", "Decision") + ": " + root.valueOrUnavailable(root.riskValue(combinedRisk, "decision")); pillTone: "details" }
                            InfoPill { textValue: root.trx("Risk", "Risk") + ": " + root.numberOrUnavailable(root.riskValue(combinedRisk, "risk")); pillTone: "details" }
                            InfoPill { textValue: root.trx("Can lock", "Can lock") + ": " + root.boolLabel(combinedRisk.can_lock); pillTone: "success" }
                        }
                        Label { text: root.trx("Model family", "Model family") + ": " + root.valueOrUnavailable(combinedRisk.model_family); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: root.trx("Source", "Source") + ": " + root.valueOrUnavailable(combinedRisk.source); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: root.trx("Reason codes", "Reason codes") + ": " + root.listText(combinedRisk.reason_codes); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
            }


            GlassCard {
                objectName: "hybridDirectCandidateGroupsCard"
                Layout.fillWidth: true
                implicitHeight: candidateGroupsColumn.implicitHeight + 32

                ColumnLayout {
                    id: candidateGroupsColumn
                    anchors.fill: parent
                    anchors.margins: root.compactLayout ? 16 : 22
                    spacing: 12

                    SectionHeader {
                        title: root.trx("Candidate groups and results", "Candidate groups and results")
                        subtitle: root.trx(
                            "يعرض QML بيانات candidates والmetrics كما يرسلها الباكند فقط. لا يحسب QML scores أو AUC/EER/FAR/FRR أو group votes.",
                            "QML renders backend-owned candidate and metric state only. It does not compute scores, AUC/EER/FAR/FRR, or group votes."
                        )
                        Layout.fillWidth: true
                    }

                    Label {
                        objectName: "hybridDirectCandidateGroupNamesLabel"
                        text: root.trx(
                            "Classic Candidates | Keyboard Candidates | Mouse Candidates | One-Class Deep Candidates | Combined Candidates | Fusion Candidates",
                            "Classic Candidates | Keyboard Candidates | Mouse Candidates | One-Class Deep Candidates | Combined Candidates | Fusion Candidates"
                        )
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    Rectangle {
                        objectName: "hybridDirectNoReportNotice"
                        Layout.fillWidth: true
                        visible: latestReportState && latestReportState.available === false
                        radius: 18
                        color: Qt.rgba(214 / 255, 168 / 255, 79 / 255, theme.isDark ? 0.12 : 0.08)
                        border.color: Qt.rgba(214 / 255, 168 / 255, 79 / 255, theme.isDark ? 0.38 : 0.28)
                        border.width: 1
                        implicitHeight: noReportNoticeLabel.implicitHeight + 24

                        Label {
                            id: noReportNoticeLabel
                            anchors.fill: parent
                            anchors.margins: 12
                            text: root.trx(
                                "لم يتم توليد تقرير بعد. شغّل Hybrid Direct Test لعرض نتائج المرشحين.",
                                "No report generated yet. Run Hybrid Direct Test to populate candidate results."
                            )
                            color: theme.text
                            wrapMode: Text.Wrap
                            verticalAlignment: Text.AlignVCenter
                        }
                    }

                    Repeater {
                        model: root.candidateGroups
                        delegate: ColumnLayout {
                            property var groupPayload: modelData || ({})
                            Layout.fillWidth: true
                            spacing: 10

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10

                                Label {
                                    text: root.valueOrUnavailable(groupPayload.title)
                                    color: theme.text
                                    font.pixelSize: root.compactLayout ? 16 : 18
                                    font.bold: true
                                    Layout.fillWidth: true
                                    wrapMode: Text.Wrap
                                }

                                InfoPill {
                                    textValue: root.valueOrUnavailable(groupPayload.candidate_count) + " " + root.trx("مرشحين", "candidates")
                                    pillTone: "details"
                                }
                            }

                            Label {
                                text: root.trx(
                                    "كل بطاقة تعرض قيم الباكند كما هي: لا حسابات أو تصويت أو ترتيب داخل QML.",
                                    "Each card displays backend values as-is: no scoring, voting, or ranking is computed in QML."
                                )
                                color: theme.muted
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }

                            GridLayout {
                                objectName: "hybridDirectCandidateRows"
                                Layout.fillWidth: true
                                columns: root.compactLayout ? 1 : 2
                                columnSpacing: 14
                                rowSpacing: 14

                                Repeater {
                                    model: groupPayload.candidates || []
                                    delegate: Rectangle {
                                        id: candidateCard
                                        objectName: "hybridDirectCandidateResultCard"
                                        property var candidatePayload: modelData || ({})
                                        property string statusText: root.rowValue(candidatePayload, "status")
                                        property string decisionText: root.rowValue(candidatePayload, "decision")
                                        property string artifactText: root.rowValue(candidatePayload, "artifact")
                                        Layout.fillWidth: true
                                        Layout.preferredWidth: root.compactLayout ? candidateGroupsColumn.width : Math.max(360, (candidateGroupsColumn.width - 14) / 2)
                                        implicitHeight: candidateCardColumn.implicitHeight + 28
                                        radius: 22
                                        color: theme.surface1 || theme.surface
                                        border.color: theme.glassBorder || theme.border
                                        border.width: 1

                                        ColumnLayout {
                                            id: candidateCardColumn
                                            anchors.fill: parent
                                            anchors.margins: root.compactLayout ? 12 : 14
                                            spacing: 10

                                            RowLayout {
                                                Layout.fillWidth: true
                                                spacing: 8

                                                ColumnLayout {
                                                    Layout.fillWidth: true
                                                    spacing: 3

                                                    Label {
                                                        text: root.rowValue(candidatePayload, "display_name")
                                                        color: theme.text
                                                        font.pixelSize: root.compactLayout ? 14 : 16
                                                        font.bold: true
                                                        wrapMode: Text.Wrap
                                                        Layout.fillWidth: true
                                                    }
                                                    Label {
                                                        text: root.trx("Group", "Group") + ": " + root.rowValue(candidatePayload, "group")
                                                        color: theme.muted
                                                        font.pixelSize: root.compactLayout ? 11 : 12
                                                        wrapMode: Text.Wrap
                                                        Layout.fillWidth: true
                                                    }
                                                }

                                                InfoPill {
                                                    textValue: candidateCard.statusText
                                                    pillTone: root.statusTone(candidateCard.statusText)
                                                }
                                            }

                                            Flow {
                                                Layout.fillWidth: true
                                                spacing: 8
                                                InfoPill { textValue: root.trx("Decision", "Decision") + ": " + candidateCard.decisionText; pillTone: root.decisionTone(candidateCard.decisionText) }
                                                InfoPill { textValue: root.trx("Risk", "Risk") + ": " + root.displayValue(candidatePayload.risk); pillTone: "details" }
                                                InfoPill { textValue: root.trx("Can Vote", "Can Vote") + ": " + root.boolLabel(candidatePayload.can_vote); pillTone: candidatePayload.can_vote === true ? "success" : "warn" }
                                                InfoPill { textValue: root.trx("Artifact", "Artifact") + ": " + candidateCard.artifactText; pillTone: root.artifactTone(candidateCard.artifactText) }
                                                InfoPill { textValue: root.trx("Latency", "Latency") + ": " + root.displayValue(candidatePayload.latency_ms); pillTone: "details" }
                                            }

                                            GridLayout {
                                                Layout.fillWidth: true
                                                columns: root.compactLayout ? 1 : 2
                                                columnSpacing: 12
                                                rowSpacing: 6

                                                Label {
                                                    text: "AUC / EER: " + root.pairText(candidatePayload.auc, candidatePayload.eer)
                                                    color: theme.text
                                                    wrapMode: Text.Wrap
                                                    Layout.fillWidth: true
                                                }
                                                Label {
                                                    text: "FAR / FRR: " + root.pairText(candidatePayload.far, candidatePayload.frr)
                                                    color: theme.text
                                                    wrapMode: Text.Wrap
                                                    Layout.fillWidth: true
                                                }
                                            }

                                            Rectangle {
                                                Layout.fillWidth: true
                                                implicitHeight: 1
                                                color: theme.border
                                                opacity: 0.55
                                            }

                                            Label {
                                                text: root.trx("Reason", "Reason") + ": " + root.rowValue(candidatePayload, "reason")
                                                color: theme.muted
                                                wrapMode: Text.Wrap
                                                Layout.fillWidth: true
                                            }
                                            Label {
                                                text: root.trx("Metrics", "Metrics") + ": " + root.rowValue(candidatePayload, "metrics_reason")
                                                color: theme.muted
                                                wrapMode: Text.Wrap
                                                Layout.fillWidth: true
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            GlassCard {
                objectName: "hybridDirectGroupVotesCard"
                Layout.fillWidth: true
                implicitHeight: groupVotesColumn.implicitHeight + 32

                ColumnLayout {
                    id: groupVotesColumn
                    anchors.fill: parent
                    anchors.margins: root.compactLayout ? 16 : 22
                    spacing: 12

                    SectionHeader {
                        title: root.trx("Group Votes", "Group Votes")
                        subtitle: root.trx(
                            "هذه group votes تأتي من report backend فقط. عدة keyboard candidates لا تتحول إلى عدة أصوات مستقلة داخل QML.",
                            "These group votes come from backend reports only. Multiple keyboard candidates do not become multiple independent votes in QML."
                        )
                        Layout.fillWidth: true
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: root.compactLayout ? 2 : 8
                        columnSpacing: 10
                        rowSpacing: 6
                        Label { text: root.trx("Group", "Group"); color: theme.muted; font.bold: true }
                        Label { text: root.trx("Selected", "Selected"); color: theme.muted; font.bold: true }
                        Label { text: root.trx("Decision", "Decision"); color: theme.muted; font.bold: true }
                        Label { text: root.trx("Risk", "Risk"); color: theme.muted; font.bold: true }
                        Label { text: root.trx("Confidence", "Confidence"); color: theme.muted; font.bold: true }
                        Label { text: root.trx("Offline State", "Offline State"); color: theme.muted; font.bold: true }
                        Label { text: root.trx("Face would be required", "Face would be required"); color: theme.muted; font.bold: true }
                        Label { text: root.trx("Reason", "Reason"); color: theme.muted; font.bold: true }
                    }

                    Repeater {
                        model: root.groupVotes
                        delegate: GridLayout {
                            property var votePayload: modelData || ({})
                            Layout.fillWidth: true
                            columns: root.compactLayout ? 2 : 8
                            columnSpacing: 10
                            rowSpacing: 6
                            Label { text: root.rowValue(votePayload, "group"); color: theme.text; wrapMode: Text.Wrap }
                            Label { text: root.rowValue(votePayload, "selected_candidate_id"); color: theme.text; wrapMode: Text.Wrap }
                            Label { text: root.rowValue(votePayload, "decision"); color: theme.text; wrapMode: Text.Wrap }
                            Label { text: root.displayValue(votePayload.risk); color: theme.text; wrapMode: Text.Wrap }
                            Label { text: root.displayValue(votePayload.confidence); color: theme.text; wrapMode: Text.Wrap }
                            Label { text: root.rowValue(votePayload, "offline_state"); color: theme.text; wrapMode: Text.Wrap }
                            Label { text: root.boolLabel(votePayload.face_required_report_only); color: theme.text; wrapMode: Text.Wrap }
                            Label { text: root.rowValue(votePayload, "reason"); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        }
                    }
                }
            }

            GlassCard {
                objectName: "hybridLiveCandidateObserverCard"
                Layout.fillWidth: true
                implicitHeight: liveObserverColumn.implicitHeight + 32

                ColumnLayout {
                    id: liveObserverColumn
                    anchors.fill: parent
                    anchors.margins: root.compactLayout ? 16 : 22
                    spacing: 12

                    SectionHeader {
                        title: root.trx("Live Candidate Observer", "Live Candidate Observer")
                        subtitle: root.trx(
                            "مراقب لايف report-only مملوك للباكند. يعرض snapshot rows أثناء الجلسة ولا يحسب readiness أو lock داخل QML.",
                            "Backend-owned report-only live observer. It displays snapshot rows during the session and does not compute readiness or lock decisions in QML."
                        )
                        Layout.fillWidth: true
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 10
                        InfoPill { objectName: "hybridLiveObserverRunningPill"; textValue: root.trx("Running", "Running") + ": " + root.boolLabel(liveCandidateObserverState.observer_running); pillTone: "details" }
                        InfoPill { objectName: "hybridLiveObserverUpdatedPill"; textValue: root.trx("Last update", "Last update") + ": " + root.valueOrUnavailable(liveCandidateObserverState.last_update_at); pillTone: "details" }
                        InfoPill { objectName: "hybridLiveObserverRowsPill"; textValue: root.trx("Rows", "Rows") + ": " + root.valueOrUnavailable((liveCandidateObserverState.candidate_rows || []).length); pillTone: "details" }
                        InfoPill { objectName: "hybridLiveObserverSafetyPill"; textValue: root.trx("Runtime authoritative", "Runtime authoritative") + ": " + root.boolLabel(liveCandidateObserverState.runtime_authoritative); pillTone: liveCandidateObserverState.runtime_authoritative === true ? "danger" : "success" }
                    }

                    Label {
                        objectName: "hybridLiveObserverReportPathLabel"
                        text: root.trx("Observer report", "Observer report") + ": " + root.valueOrUnavailable(liveCandidateObserverState.observer_report_path)
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    Label {
                        objectName: "hybridLiveObserverWarningsLabel"
                        text: root.trx("Warnings", "Warnings") + ": " + root.listText(liveCandidateObserverState.observer_warnings)
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    GridLayout {
                        objectName: "hybridLiveObserverTableHeader"
                        Layout.fillWidth: true
                        columns: root.denseWindow ? 2 : 8
                        columnSpacing: 10
                        rowSpacing: 8
                        visible: (liveCandidateObserverState.candidate_rows || []).length > 0

                        Label { text: root.trx("Candidate", "Candidate"); color: theme.muted; font.bold: true }
                        Label { text: root.trx("Status", "Status"); color: theme.muted; font.bold: true }
                        Label { text: root.trx("Risk", "Risk"); color: theme.muted; font.bold: true; visible: !root.denseWindow }
                        Label { text: root.trx("Decision", "Decision"); color: theme.muted; font.bold: true; visible: !root.denseWindow }
                        Label { text: root.trx("Can vote", "Can vote"); color: theme.muted; font.bold: true; visible: !root.denseWindow }
                        Label { text: root.trx("Artifact", "Artifact"); color: theme.muted; font.bold: true; visible: !root.denseWindow }
                        Label { text: root.trx("Latency", "Latency"); color: theme.muted; font.bold: true; visible: !root.denseWindow }
                        Label { text: root.trx("Reason", "Reason"); color: theme.muted; font.bold: true }
                    }

                    Repeater {
                        objectName: "hybridLiveObserverRowsRepeater"
                        model: liveCandidateObserverState.candidate_rows || []
                        delegate: GridLayout {
                            Layout.fillWidth: true
                            columns: root.denseWindow ? 2 : 8
                            columnSpacing: 10
                            rowSpacing: 8
                            property var observerRow: modelData || ({})

                            Label { text: root.rowValue(observerRow, "candidate_id"); color: theme.text; wrapMode: Text.Wrap }
                            Label { text: root.rowValue(observerRow, "status"); color: theme.text; wrapMode: Text.Wrap }
                            Label { text: root.displayValue(observerRow.risk); color: theme.text; wrapMode: Text.Wrap; visible: !root.denseWindow }
                            Label { text: root.rowValue(observerRow, "decision"); color: theme.text; wrapMode: Text.Wrap; visible: !root.denseWindow }
                            Label { text: root.boolLabel(observerRow.can_vote); color: theme.text; wrapMode: Text.Wrap; visible: !root.denseWindow }
                            Label { text: root.rowValue(observerRow, "artifact_status"); color: theme.text; wrapMode: Text.Wrap; visible: !root.denseWindow }
                            Label { text: root.displayValue(observerRow.latency_ms); color: theme.text; wrapMode: Text.Wrap; visible: !root.denseWindow }
                            Label { text: root.rowValue(observerRow, "reason"); color: theme.muted; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        }
                    }
                }
            }

            GlassCard {
                objectName: "hybridDirectLatestReportsCard"
                Layout.fillWidth: true
                implicitHeight: latestReportsColumn.implicitHeight + 32

                ColumnLayout {
                    id: latestReportsColumn
                    anchors.fill: parent
                    anchors.margins: root.compactLayout ? 16 : 22
                    spacing: 12

                    SectionHeader {
                        title: root.trx("Latest Reports", "Latest Reports")
                        subtitle: root.trx(
                            "No report generated yet تظهر عندما لا يرسل الباكند report state. التقارير offline review فقط ولا تختار production winner.",
                            "No report generated yet is shown when the backend has no report state. Reports are offline review only and do not select a production winner."
                        )
                        Layout.fillWidth: true
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 10
                        InfoPill { objectName: "hybridDirectLatestReportStatusPill"; textValue: root.rowValue(latestReportState, "message"); pillTone: latestReportState.available ? "success" : "details" }
                        InfoPill { objectName: "hybridDirectLatestReportSourcePill"; textValue: root.trx("Source", "Source") + ": " + root.valueOrUnavailable(latestReportState.source); pillTone: "details" }
                        InfoPill { objectName: "hybridDirectLatestReportRunStatusPill"; textValue: root.trx("Run status", "Run status") + ": " + root.valueOrUnavailable(latestReportState.run_status); pillTone: "details" }
                        InfoPill { textValue: root.trx("Sessions", "Sessions") + ": " + root.valueOrUnavailable(latestReportState.session_count); pillTone: "details" }
                        InfoPill { textValue: root.trx("Candidate rows", "Candidate rows") + ": " + root.valueOrUnavailable(latestReportState.candidate_result_rows); pillTone: "details" }
                        InfoPill { textValue: root.trx("Model rows", "Model rows") + ": " + root.valueOrUnavailable(latestReportState.model_rows); pillTone: "details" }
                    }

                    Label {
                        objectName: "hybridDirectLatestReportPathLabel"
                        text: root.trx("Summary", "Summary") + ": " + root.valueOrUnavailable(latestReportState.summary_path)
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                }
            }

            GlassCard {
                objectName: "hybridDirectFusionProvenanceCard"
                Layout.fillWidth: true
                implicitHeight: fusionColumn.implicitHeight + 32

                ColumnLayout {
                    id: fusionColumn
                    anchors.fill: parent
                    anchors.margins: root.compactLayout ? 16 : 22
                    spacing: 12

                    SectionHeader {
                        title: root.trx("Fusion and final-action provenance", "Fusion and final-action provenance")
                        subtitle: root.trx(
                            "هذه القيم تأتي من الباكند. الصفحة لا تستنتج Green/Amber/Red أو lock/no-lock محليًا.",
                            "These values come from the backend state; the page does not infer Green/Amber/Red or lock/no-lock locally."
                        )
                        Layout.fillWidth: true
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 10
                        InfoPill { objectName: "hybridDirectFusionStatePill"; textValue: root.trx("Fusion State", "Fusion State") + ": " + root.valueOrUnavailable(hybridState.fusion_state); pillTone: "info" }
                        InfoPill { objectName: "hybridDirectAgreementPill"; textValue: root.trx("Agreement count", "Agreement count") + ": " + root.valueOrUnavailable(hybridState.agreement_count); pillTone: "details" }
                        InfoPill { objectName: "hybridDirectFinalDecisionPill"; textValue: root.trx("Final decision", "Final decision") + ": " + root.valueOrUnavailable(hybridState.final_action); pillTone: "warn" }
                        InfoPill { objectName: "hybridDirectLatencyPill"; textValue: root.trx("Latency", "Latency") + ": " + root.valueOrUnavailable(hybridState.latency_ms) + " ms"; pillTone: "details" }
                    }

                    Label {
                        objectName: "hybridDirectDivergenceReasonLabel"
                        text: root.trx("Divergence reason", "Divergence reason") + ": " + root.valueOrUnavailable(hybridState.divergence_reason)
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Label {
                        objectName: "hybridDirectReasonCodesLabel"
                        text: root.trx("Reason codes", "Reason codes") + ": " + root.listText(hybridState.reason_codes)
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                    Label {
                        objectName: "hybridDirectErrorsLabel"
                        text: root.trx("Errors", "Errors") + ": " + root.listText(hybridState.errors)
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                }
            }

            GlassCard {
                objectName: "hybridDirectSafetyGateCard"
                Layout.fillWidth: true
                implicitHeight: gateColumn.implicitHeight + 32

                ColumnLayout {
                    id: gateColumn
                    anchors.fill: parent
                    anchors.margins: root.compactLayout ? 16 : 22
                    spacing: 12

                    SectionHeader {
                        title: root.trx("Safety gate status", "Safety gate status")
                        subtitle: root.trx(
                            "حالات البوابات وسببها من safety_gate_results. QML does not decide pass/fail.",
                            "Gate status and reasons come from safety_gate_results. QML does not decide pass/fail."
                        )
                        Layout.fillWidth: true
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: root.compactLayout ? 1 : 2
                        columnSpacing: 12
                        rowSpacing: 12

                        Label { text: "Direct control: " + root.valueOrUnavailable(root.gateValue("developer_direct_enabled", "status")) + " | " + root.gateCodes("developer_direct_enabled"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: "Evaluation Harness: " + root.valueOrUnavailable(root.gateValue("evaluation_harness", "status")) + " | " + root.gateCodes("evaluation_harness"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: "Thresholds: " + root.valueOrUnavailable(root.gateValue("thresholds_calibrated", "status")) + " | " + root.gateCodes("thresholds_calibrated"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: "Face Confirmation: " + root.valueOrUnavailable(root.gateValue("face_confirmation", "status")) + " | " + root.gateCodes("face_confirmation"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: "Rollback: " + root.valueOrUnavailable(root.gateValue("rollback_snapshot", "status")) + " | " + root.gateCodes("rollback_snapshot"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: "No single model lock: " + root.valueOrUnavailable(root.gateValue("no_single_model_lock", "status")) + " | " + root.gateCodes("no_single_model_lock"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: "Experiment can lock alone false: " + root.valueOrUnavailable(root.gateValue("experiment_can_lock_alone_false", "status")) + " | " + root.gateCodes("experiment_can_lock_alone_false"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                        Label { text: "Device influence: " + root.valueOrUnavailable(root.gateValue("device_influence", "status")) + " | " + root.gateCodes("device_influence"); color: theme.text; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
            }

            GlassCard {
                objectName: "hybridDirectDeveloperLiveModeCard"
                Layout.fillWidth: true
                implicitHeight: developerLiveColumn.implicitHeight + 32

                ColumnLayout {
                    id: developerLiveColumn
                    anchors.fill: parent
                    anchors.margins: root.compactLayout ? 16 : 22
                    spacing: 12

                    SectionHeader {
                        title: root.trx("Direct Live Control", "Direct Live Control")
                        subtitle: root.trx(
                            "Live mode منفصل ومقفل ببوابات safety. أي lock يحتاج backend safety gates و Face Confirmation قبل lock، وليس Run Hybrid Direct Test.",
                            "Live mode is separate and safety-gated. Any lock path requires backend safety gates and Face Confirmation before lock; Run Hybrid Direct Test never enables it."
                        )
                        Layout.fillWidth: true
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 10
                        InfoPill { textValue: root.trx("Gated", "Gated") + ": " + root.valueOrUnavailable(root.gateValue("developer_direct_enabled", "status")); pillTone: "warn" }
                        InfoPill { textValue: root.trx("Face Confirmation", "Face Confirmation") + ": " + root.valueOrUnavailable(root.gateValue("face_confirmation", "status")); pillTone: "warn" }
                        InfoPill { textValue: root.trx("Device influence", "Device influence") + ": " + root.valueOrUnavailable(root.gateValue("device_influence", "status")); pillTone: "details" }
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 10
                        AppButton { objectName: "hybridDirectEnableButton"; text: root.trx("Enable Direct Live Control", "Enable Direct Live Control"); role: "warn"; enabled: false; debugLabel: "Direct Live Control remains gated by backend safety requirements" }
                        AppButton { objectName: "hybridDirectDisableButton"; text: root.trx("Disable Hybrid Now", "Disable Hybrid Now"); role: "danger"; enabled: false; debugLabel: "No live hybrid mode is enabled from this page" }
                    }

                    Label {
                        text: root.trx(
                            "هذه المنطقة ليست Run Hybrid Direct Test. لا يتم تفعيل live behavior أو lock policy من C9.",
                            "This area is not Run Hybrid Direct Test. C9 does not enable live behavior or lock policy."
                        )
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                }
            }

            GlassCard {
                objectName: "hybridDirectControlSurfaceCard"
                Layout.fillWidth: true
                implicitHeight: controlsColumn.implicitHeight + 32

                ColumnLayout {
                    id: controlsColumn
                    anchors.fill: parent
                    anchors.margins: root.compactLayout ? 16 : 22
                    spacing: 12

                    SectionHeader {
                        title: root.trx("Controls", "Controls")
                        subtitle: root.trx(
                            "Run Hybrid Direct Test هو تشغيل test/replay/offline-style عبر مسار monitor في وضع آمن: لا قفل، لا Face Confirmation، ولا تأثير على الجهاز. Direct Live Control منفصل ومغلق.",
                            "Run Hybrid Direct Test is a test/replay/offline-style monitor evaluation: no lock, no Face Confirmation, and no device influence. Direct Live Control is separate and remains gated off."
                        )
                        Layout.fillWidth: true
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 10
                        AppButton {
                            objectName: "hybridDirectRunDecisionButton"
                            text: backend.hybridDirectTestRunning ? root.trx("Hybrid Test Running", "Hybrid Test Running") : root.trx("Run Hybrid Direct Test", "Run Hybrid Direct Test")
                            role: "info"
                            enabled: backend.canRunHybridDirectTest
                            debugLabel: backend.hybridDirectTestUnavailableReason
                            onClicked: backend.runHybridDirectTest()
                        }
                        AppButton {
                            objectName: "hybridLiveSessionEvalButton"
                            text: backend.hybridDirectTestRunning ? root.trx("Evaluation Running", "Evaluation Running") : root.trx("Evaluate Latest Live Session", "Evaluate Latest Live Session")
                            role: "info"
                            enabled: backend.canRunHybridDirectTest
                            debugLabel: root.trx("Runs the latest archived session through all registered candidates in report-only mode.", "Runs the latest archived session through all registered candidates in report-only mode.")
                            onClicked: backend.evaluateLatestHybridLiveSession()
                        }
                        AppButton {
                            objectName: "hybridDirectOpenLatestReportButton"
                            text: root.trx("Open Latest Report", "Open Latest Report")
                            role: "details"
                            enabled: latestReportState.available === true
                            debugLabel: latestReportState.message
                            onClicked: backend.openLatestHybridDirectReport()
                        }
                        AppButton {
                            objectName: "hybridOpenLatestLiveSessionEvalReportButton"
                            text: root.trx("Open Live Eval Report", "Open Live Eval Report")
                            role: "details"
                            enabled: latestLiveSessionEvalReportState.available === true
                            debugLabel: latestLiveSessionEvalReportState.message
                            onClicked: backend.openLatestHybridLiveSessionEvalReport()
                        }
                        AppButton {
                            objectName: "hybridDirectExportLogButton"
                            text: root.trx("Export CSV", "Export CSV")
                            role: "details"
                            enabled: latestReportState.available === true
                            debugLabel: latestReportState.message
                            onClicked: backend.exportHybridDirectCsv()
                        }
                        AppButton {
                            objectName: "hybridDirectClearTestResultsButton"
                            text: root.trx("Clear Test Results", "Clear Test Results")
                            role: "warn"
                            enabled: latestReportState.available === true || latestResult.passed !== undefined
                            debugLabel: root.trx("Clears in-memory display state only; report files are preserved.", "Clears in-memory display state only; report files are preserved.")
                            onClicked: backend.clearHybridDirectTestResults()
                        }
                    }

                    Label {
                        objectName: "hybridDirectControlsUnavailableLabel"
                        text: backend.hybridDirectTestRunning
                              ? root.trx("Hybrid Direct Test is running in safe test-only mode.", "Hybrid Direct Test is running in safe test-only mode.")
                              : (backend.canRunHybridDirectTest
                                 ? root.trx("Ready to run a safe test/replay/offline-style Hybrid Direct Test.", "Ready to run a safe test/replay/offline-style Hybrid Direct Test.")
                                 : backend.hybridDirectTestUnavailableReason)
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    Label {
                        objectName: "hybridDirectLatestResultLabel"
                        text: root.trx("Latest result", "Latest result") + ": " + root.valueOrUnavailable(latestResult.passed)
                        color: latestResult.passed === true ? theme.success : theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    Label {
                        objectName: "hybridDirectLatestReasonCodesLabel"
                        text: root.trx("Latest reason codes", "Latest reason codes") + ": " + root.listText(latestResult.reason_codes)
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    Label {
                        objectName: "hybridLiveSessionEvalLatestStatusLabel"
                        text: root.trx("Latest live-session eval", "Latest live-session eval")
                              + ": " + root.valueOrUnavailable(latestLiveSessionEvalResult.status)
                              + " · " + root.trx("Rows", "Rows") + ": " + root.valueOrUnavailable(latestLiveSessionEvalResult.candidate_result_rows)
                        color: latestLiveSessionEvalReportState.available === true ? theme.success : theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    Label {
                        objectName: "hybridLiveSessionEvalReasonCodesLabel"
                        text: root.trx("Live eval reason codes", "Live eval reason codes") + ": " + root.listText(latestLiveSessionEvalResult.reason_codes)
                        color: theme.muted
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }
                }
            }
        }
    }
}
