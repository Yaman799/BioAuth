import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"

GlassCard {
    id: licenseCard
    property var controller
    property var theme
    property var rootWindow
    property string resultMessage: ""
    property bool resultOk: false

    readonly property bool licenseDark: !(theme && theme.isDark === false)
    readonly property color licensePanelBg: licenseDark ? "#b20d1626" : ((theme && theme.surface1) ? theme.surface1 : "#eff5fc")
    readonly property color licensePanelBgAlt: licenseDark ? "#cc0f192b" : ((theme && theme.inputBg) ? theme.inputBg : "#eef4fd")
    readonly property color licensePanelBorder: licenseDark ? "#4d22d3ee" : ((theme && theme.border) ? theme.border : "#c9d8ea")
    readonly property color licensePanelBorderSoft: licenseDark ? "#334563" : ((theme && theme.border) ? theme.border : "#d8e3f2")
    readonly property color licenseText: licenseDark ? "#f8fbff" : ((theme && theme.text) ? theme.text : "#0f172a")
    readonly property color licenseMutedText: licenseDark ? "#9fb2ce" : ((theme && theme.muted) ? theme.muted : "#52627a")
    readonly property color licensePlaceholderText: licenseDark ? "#7890ad" : ((theme && theme.muted) ? theme.muted : "#718096")
    readonly property color licenseFocusBorder: (theme && theme.accent) ? theme.accent : "#22d3ee"
    readonly property color licenseSuccessText: (theme && theme.success) ? theme.success : "#22c55e"
    readonly property color licenseWarningText: (theme && theme.warn) ? theme.warn : "#f59e0b"
    readonly property var licenseTheme: ({
        isDark: licenseCard.licenseDark,
        text: licenseCard.licenseText,
        muted: licenseCard.licenseMutedText,
        primary: (theme && theme.primary) ? theme.primary : "#2563eb",
        primaryHover: (theme && theme.primaryHover) ? theme.primaryHover : "#1d4ed8",
        success: (theme && theme.success) ? theme.success : "#22c55e",
        warn: (theme && theme.warn) ? theme.warn : "#f59e0b",
        danger: (theme && theme.danger) ? theme.danger : "#ef4444",
        info: (theme && theme.info) ? theme.info : "#38bdf8",
        border: licenseCard.licensePanelBorderSoft,
        surface: licenseCard.licensePanelBg,
        surface1: licenseCard.licensePanelBg,
        surface2: licenseCard.licensePanelBgAlt,
        inputBg: licenseCard.licensePanelBgAlt,
        neutralBg: licenseCard.licenseDark ? "#25334d" : "#dce5f3",
        neutralHover: licenseCard.licenseDark ? "#30415f" : "#d1dceb",
        neutralPressed: licenseCard.licenseDark ? "#1a2436" : "#c7d5e8",
        neutralBorder: licenseCard.licenseDark ? "#3b4f71" : "#cad7ea"
    })

    function trx(arText, enText) { return controller ? controller.trx(arText, enText) : enText }
    function statusValue(key, fallbackValue) {
        var status = backend.licenseStatus || ({})
        var value = status[key]
        if (value === undefined || value === null || value === "") return fallbackValue
        return value
    }
    function yesNo(value) { return value ? trx("نعم", "Yes") : trx("لا", "No") }
    function licenseStateTone() {
        var state = String(statusValue("state", "missing_basic") || "").toLowerCase()
        if (state === "licensed" || state === "trial_active") return "success"
        if (state === "grace_active") return "warn"
        if (state.indexOf("expired") >= 0 || state.indexOf("invalid") >= 0 || state.indexOf("malformed") >= 0) return "danger"
        return "info"
    }
    function licenseStateText() {
        var state = String(statusValue("state", "missing_basic") || "missing_basic")
        if (state === "licensed") return trx("ترخيص نشط. تتحقق BioAuth محليًا بالمفتاح العام فقط.", "License is active. BioAuth verifies it locally with the public key only.")
        if (state === "trial_active") return trx("الفترة التجريبية نشطة. تبقى ميزات Basic آمنة دائمًا.", "Trial is active. Basic safety features always remain available.")
        if (state === "grace_active") return trx("فترة السماح نشطة. جهّز ترخيصًا موقّعًا قبل انتهاء المهلة.", "Grace period is active. Prepare a signed license before the grace window ends.")
        if (state.indexOf("expired") >= 0) return trx("انتهى الترخيص. يعمل BioAuth في Basic safety mode بدون حذف بياناتك.", "License expired. BioAuth runs in Basic safety mode without deleting your data.")
        if (state.indexOf("invalid") >= 0 || state.indexOf("malformed") >= 0) return trx("الترخيص غير صالح أو malformed. لم يتم عرض أي كود ترخيص خام.", "License is invalid or malformed. No raw license code is displayed.")
        return trx("لا يوجد ترخيص مثبت. تبقى الحماية الأساسية والاسترداد والحذف المحلي متاحة.", "No license is installed. Basic protection, recovery, and local deletion remain available.")
    }
    function featureSummary() {
        var status = backend.licenseStatus || ({})
        var features = status.features || ({})
        var enabled = []
        if (features.basic_protection) enabled.push(trx("الحماية الأساسية", "Basic protection"))
        if (features.local_recovery) enabled.push(trx("الاسترداد المحلي", "Local recovery"))
        if (features.view_history_basic) enabled.push(trx("السجل الأساسي", "Basic history"))
        if (features.advanced_reports) enabled.push(trx("التقارير المتقدمة", "Advanced reports"))
        if (features.incident_evidence_capture) enabled.push(trx("أدلة الحوادث", "Incident evidence"))
        if (features.shadow_learning_controls) enabled.push(trx("تحكم التعلم الظلي", "Shadow learning controls"))
        if (features.team_policy_controls) enabled.push(trx("سياسات الفريق", "Team policy controls"))
        return enabled.length > 0 ? enabled.join(" • ") : trx("ميزات Basic الآمنة متاحة دائماً.", "Safe Basic features are always available.")
    }
    function activateFromPaste() {
        var result = backend.activateLicense(licenseCodeInput.text)
        resultOk = result && result.ok
        resultMessage = (result && result.message) ? result.message : trx("تعذر تفعيل الترخيص.", "License activation failed.")
        if (resultOk) licenseCodeInput.text = ""
    }
    function importFromPath() {
        var result = backend.importLicenseFile(licensePathInput.text)
        resultOk = result && result.ok
        resultMessage = (result && result.message) ? result.message : trx("تعذر استيراد ملف الترخيص.", "License import failed.")
        if (resultOk) licensePathInput.text = ""
    }

    color: licenseDark ? ((theme && theme.glassBg) ? theme.glassBg : "#b20d1626") : ((theme && theme.glassBg) ? theme.glassBg : "#d9ffffff")
    border.color: licenseDark ? ((theme && theme.glassBorder) ? theme.glassBorder : "#4d22d3ee") : ((theme && theme.glassBorder) ? theme.glassBorder : "#c9d8ea")

    Layout.fillWidth: true
    implicitHeight: licenseContent.implicitHeight + 40

    ColumnLayout {
        id: licenseContent
        anchors.fill: parent
        anchors.margins: 20
        spacing: 14

        SectionHeader {
            theme: licenseCard.licenseTheme
            title: trx("License & plan", "License & plan")
            subtitle: trx("سياسة الإنتاج الحالية: تراخيص موقّعة تعمل دون اتصال. لا يوجد إبطال فوري عبر الشبكة في هذا الإصدار.", "Current production policy: offline signed licenses. Instant online revocation is not supported in this build.")
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: currentLicenseSummary.implicitHeight + 28
            radius: 18
            color: licenseCard.licensePanelBg
            border.color: licenseCard.licensePanelBorder
            border.width: 1

            ColumnLayout {
                id: currentLicenseSummary
                anchors.fill: parent
                anchors.margins: 14
                spacing: 8

                GridLayout {
                    Layout.fillWidth: true
                    columns: width >= 760 ? 4 : 2
                    columnSpacing: 10
                    rowSpacing: 8
                    InfoPill { theme: licenseCard.licenseTheme; textValue: trx("Tier", "Tier") + ": " + String(licenseCard.statusValue("effective_tier", "free")).toUpperCase(); pillTone: backend.licenseStatus && backend.licenseStatus.premium_active ? "success" : "neutral" }
                    InfoPill { theme: licenseCard.licenseTheme; textValue: trx("State", "State") + ": " + licenseCard.statusValue("state", "missing_basic"); pillTone: licenseCard.licenseStateTone() }
                    InfoPill { theme: licenseCard.licenseTheme; textValue: trx("Premium", "Premium") + ": " + licenseCard.yesNo(backend.licenseStatus && backend.licenseStatus.premium_active); pillTone: backend.licenseStatus && backend.licenseStatus.premium_active ? "success" : "neutral" }
                    InfoPill { theme: licenseCard.licenseTheme; textValue: trx("Expiry", "Expiry") + ": " + licenseCard.statusValue("license_expires_at", "—"); pillTone: "details" }
                }

                Label {
                    Layout.fillWidth: true
                    text: licenseCard.licenseStateText()
                    color: licenseCard.licenseStateTone() === "danger" ? licenseCard.licenseWarningText : licenseCard.licenseMutedText
                    wrapMode: Text.Wrap
                }

                Label {
                    Layout.fillWidth: true
                    text: trx("Enabled features", "Enabled features") + ": " + licenseCard.featureSummary()
                    color: licenseCard.licenseText
                    wrapMode: Text.Wrap
                }
                Label {
                    Layout.fillWidth: true
                    text: licenseCard.statusValue("safe_mode_note", trx("تراخيص Basic الآمنة لا تعطل الحماية أو الحذف أو الاسترداد المحلي.", "Safe Basic licensing never disables protection, deletion, or local recovery."))
                    color: licenseCard.licenseMutedText
                    wrapMode: Text.Wrap
                }
                Label {
                    Layout.fillWidth: true
                    text: licenseCard.statusValue("revocation_note", trx("لا يوجد إبطال فوري عبر الشبكة؛ يتغير الوصول عند انتهاء الترخيص أو عند استيراد ترخيص موقّع بديل.", "No instant online revocation; access changes at signed expiry or when a replacement signed license is imported."))
                    color: licenseCard.licenseMutedText
                    wrapMode: Text.Wrap
                }
                Label {
                    Layout.fillWidth: true
                    text: licenseCard.statusValue("renewal_note", trx("التجديد يتم بلصق أو استيراد ترخيص موقّع جديد.", "Renewal is done by pasting or importing a new signed license.")) + " " + licenseCard.statusValue("clock_policy_note", trx("يعتمد انتهاء الصلاحية على ساعة الجهاز المحلية.", "Expiry is evaluated against the local device clock."))
                    color: licenseCard.licenseMutedText
                    wrapMode: Text.Wrap
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: activateLicensePanel.implicitHeight + 28
            radius: 18
            color: licenseCard.licensePanelBg
            border.color: licenseCard.licensePanelBorder
            border.width: 1

            ColumnLayout {
                id: activateLicensePanel
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10

                Label { text: trx("Paste license code", "Paste license code"); color: licenseCard.licenseText; font.bold: true }
                TextArea {
                    id: licenseCodeInput
                    Layout.fillWidth: true
                    implicitHeight: 92
                    placeholderText: "BIOAUTH-LIC-v1..."
                    wrapMode: TextEdit.WrapAnywhere
                    selectByMouse: true
                    color: licenseCard.licenseText
                    placeholderTextColor: licenseCard.licensePlaceholderText
                    background: Rectangle {
                        radius: 14
                        color: licenseCard.licensePanelBgAlt
                        border.color: licenseCodeInput.activeFocus ? licenseCard.licenseFocusBorder : licenseCard.licensePanelBorderSoft
                        border.width: licenseCodeInput.activeFocus ? 2 : 1
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    AppButton {
                        theme: licenseCard.licenseTheme
                        text: trx("Activate License", "Activate License")
                        role: "primary"
                        enabled: licenseCodeInput.text.trim().length > 0
                        onClicked: licenseCard.activateFromPaste()
                    }
                    AppButton {
                        theme: licenseCard.licenseTheme
                        text: trx("Refresh Status", "Refresh Status")
                        role: "neutral"
                        onClicked: {
                            backend.refreshLicenseStatus()
                            licenseCard.resultOk = true
                            licenseCard.resultMessage = trx("تم تحديث حالة الترخيص.", "License status refreshed.")
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: importLicensePanel.implicitHeight + 28
            radius: 18
            color: licenseCard.licensePanelBg
            border.color: licenseCard.licensePanelBorder
            border.width: 1

            ColumnLayout {
                id: importLicensePanel
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10
                Label { text: trx("Import license JSON file", "Import license JSON file"); color: licenseCard.licenseText; font.bold: true }
                AppTextField {
                    id: licensePathInput
                    theme: licenseCard.licenseTheme
                    Layout.fillWidth: true
                    placeholderText: trx("Path to license JSON or TXT file", "Path to license JSON or TXT file")
                }
                AppButton {
                    theme: licenseCard.licenseTheme
                    text: trx("Import License File", "Import License File")
                    role: "neutral"
                    enabled: licensePathInput.text.trim().length > 0
                    onClicked: licenseCard.importFromPath()
                }
            }
        }

        Label {
            Layout.fillWidth: true
            visible: licenseCard.resultMessage !== "" || (backend.licenseStatus && backend.licenseStatus.last_error)
            text: licenseCard.resultMessage !== "" ? licenseCard.resultMessage : backend.licenseStatus.last_error
            color: licenseCard.resultOk ? licenseCard.licenseSuccessText : licenseCard.licenseWarningText
            wrapMode: Text.Wrap
        }
    }
}
