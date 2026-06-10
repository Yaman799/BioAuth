import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Dialog {
    id: root
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    function trx(arText, enText) { return rootWindow ? rootWindow.trx(arText, enText) : enText }
    function trainingStatusText() {
        var visibility = String(root.sessionData.training_visibility || "not_applicable")
        if (visibility === "selected")
            return trx("مستخدمة في التدريب الحالي", "Used in current training")
        if (visibility === "counts_toward_minimum")
            return trx("تُحتسب للحد الأدنى لكن لم تُستخدم حاليًا", "Counts toward minimum but not used right now")
        if (visibility === "supplemental_selected")
            return trx("مستخدمة كجلسة داعمة إضافية", "Used as a supplemental session")
        if (visibility === "supplemental_candidate")
            return trx("مرشحة كجلسة داعمة إضافية", "Candidate for supplemental use")
        if (visibility === "supplemental_excluded")
            return trx("صالحة كدعم إضافي لكنها ليست ضمن الاختيار الحالي", "Eligible as supplemental evidence but not selected now")
        if (visibility === "blocked")
            return trx("غير مقبولة للتدريب", "Not accepted for training")
        return trx("لا تنطبق على التدريب", "Not applicable to training")
    }

    function trainingReasonText() {
        var reason = String(root.sessionData.training_block_reason || "")
        if (reason === "metadata_not_trusted")
            return trx("سبب الرفض: سلامة metadata غير موثقة، لذلك تُستبعد الجلسة من التدريب.", "Blocked because metadata integrity is not verified, so the session is ignored for training.")
        if (reason === "session_not_accepted")
            return trx("سبب الرفض: قرار الجلسة ليس legit، لذلك لا تدخل ضمن التدريب.", "Blocked because the session decision is not legit, so it cannot enter training.")
        if (reason === "session_not_completed_normally")
            return trx("سبب الرفض: الجلسة لم تنتهِ بشكل طبيعي، لذلك لا تُحتسب للتدريب.", "Blocked because the session did not end normally, so it does not count toward training.")
        if (reason === "session_without_behavior_data")
            return trx("سبب الرفض: بيانات السلوك المسجلة غير كافية.", "Blocked because the recorded behavior data is insufficient.")
        if (reason === "quality_score_below_floor")
            return trx("سبب الرفض: جودة الجلسة أقل من الحد الأدنى المطلوب للتدريب.", "Blocked because the session quality is below the training floor.")
        if (reason === "ranked_below_selection_cutoff")
            return trx("هذه الجلسة صالحة، لكن جلسات أقوى منها غطّت سعة التدريب الحالية.", "This session is valid, but stronger sessions already fill the current training budget.")
        if (reason === "protected_session_quality_low")
            return trx("الجلسة المحمية قصيرة أو ضعيفة النشاط، لذلك لا تُستخدم كجلسة داعمة إضافية.", "The protected session is too short or too inactive to be used as supplemental evidence.")
        var detail = String(root.sessionData.training_reason_detail || root.sessionData.training_selection_reason || "")
        if (detail)
            return detail
        return ""
    }
    property var sessionData: ({})
    modal: true
    anchors.centerIn: Overlay.overlay
    width: Math.max(340, Math.min(580, (rootWindow ? rootWindow.width : 720) - 32))
    height: Math.min(640, Math.max(360, (rootWindow ? rootWindow.height : 760) - 40))
    background: GlassCard { }
    header: Item {
        implicitHeight: headerColumn.implicitHeight + 24
        ColumnLayout {
            id: headerColumn
            anchors.fill: parent
            anchors.margins: 22
            spacing: 4
            Label { text: backend.tr("session_details"); color: theme.text; font.pixelSize: 24; font.bold: true; wrapMode: Text.Wrap; Layout.fillWidth: true }
            Label { text: root.sessionData.session_id || "—"; color: theme.muted; elide: Text.ElideMiddle; Layout.fillWidth: true }
        }
    }
    contentItem: ScrollView {
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ColumnLayout {
            width: root.availableWidth
            spacing: 12
            Repeater {
                model: [
                    backend.tr("session_id") + ": " + (root.sessionData.session_id || "—"),
                    backend.tr("created_at") + ": " + (root.sessionData.created_at || "—"),
                    backend.tr("session_type") + ": " + (root.sessionData.session_kind || "—"),
                    backend.tr("decision") + ": " + (root.sessionData.decision || "—"),
                    trx("Training status", "Training status") + ": " + root.trainingStatusText(),
                    trx("Training reason", "Training reason") + ": " + (root.trainingReasonText() || "—"),
                    trx("Counts toward minimum", "Counts toward minimum") + ": " + (root.sessionData.training_counts_toward_minimum ? trx("Yes", "Yes") : trx("No", "No")),
                    trx("Selected for current training", "Selected for current training") + ": " + (root.sessionData.training_selected ? trx("Yes", "Yes") : trx("No", "No")),
                    trx("Quality tier", "Quality tier") + ": " + (root.sessionData.training_quality_tier || "—"),
                    trx("Quality score", "Quality score") + ": " + ((root.sessionData.training_quality_score === undefined || root.sessionData.training_quality_score === null) ? "—" : Number(root.sessionData.training_quality_score).toFixed(3)),
                    backend.tr("keyboard_rows") + ": " + (root.sessionData.keyboard_rows || 0),
                    backend.tr("mouse_rows") + ": " + (root.sessionData.mouse_rows || 0),
                    trx("Incident evidence", "Incident evidence") + ": " + (root.sessionData.incident_evidence_available ? trx("Available", "Available") : trx("Not saved", "Not saved")),
                    trx("Evidence status", "Evidence status") + ": " + (root.sessionData.incident_evidence_status || "—"),
                    trx("Saved files", "Saved files") + ": " + (root.sessionData.incident_evidence_saved_count || 0),
                    backend.tr("folder") + ": " + (root.sessionData.path || "—")
                ]
                delegate: Rectangle {
                    Layout.fillWidth: true
                    radius: 16
                    color: theme.surface2
                    border.color: theme.border
                    implicitHeight: detailLabel.implicitHeight + 24
                    Label {
                        id: detailLabel
                        anchors.fill: parent
                        anchors.margins: 12
                        text: modelData
                        color: theme.text
                        wrapMode: Text.WrapAnywhere
                    }
                }
            }
        }
    }
    footer: Item {
        implicitHeight: footerFlow.implicitHeight + 22
        Flow {
            id: footerFlow
            anchors.fill: parent
            anchors.margins: 18
            spacing: 10
            layoutDirection: Qt.RightToLeft
            AppButton {
                text: rootWindow.trx("إغلاق", "Close")
                role: "neutral"
                onClicked: root.close()
            }
            AppButton {
                text: rootWindow.trx("فتح مجلد الأدلة", "Open evidence folder")
                role: "details"
                visible: !!root.sessionData.incident_evidence_dir
                onClicked: backend.openLocalPath(root.sessionData.incident_evidence_dir)
            }
        }
    }
    padding: 18
}
