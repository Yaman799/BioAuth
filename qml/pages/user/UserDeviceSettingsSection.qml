import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"
import "../settings"
import "../../theme/Ui.js" as Ui

GridLayout {
    id: deviceSettingsSection
    property var settingsRoot
    property var theme: settingsRoot ? settingsRoot.theme : backend.theme
    readonly property var faceState: settingsRoot ? settingsRoot.faceState : ({})
    readonly property var privacyState: settingsRoot ? settingsRoot.privacyState : ({})
    readonly property var learningState: settingsRoot ? settingsRoot.learningState : ({})
    readonly property var benchmarkState: settingsRoot ? settingsRoot.benchmarkState : ({})
    readonly property var updateState: settingsRoot ? settingsRoot.updateState : ({})
    readonly property var licenseState: settingsRoot ? settingsRoot.licenseState : ({})
    Layout.fillWidth: true
    columns: settingsRoot.compactLayout ? 1 : 2
    columnSpacing: 18
    rowSpacing: 18
    visible: settingsRoot.activeSection === "device"
    enabled: visible
    Layout.preferredHeight: visible ? implicitHeight : 0
    Layout.minimumHeight: visible ? implicitHeight : 0
    Layout.maximumHeight: visible ? 1000000 : 0

    GlassCard {
        Layout.fillWidth: true
        implicitHeight: deviceContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: deviceContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                AssetIcon { sourceUrl: settingsRoot.deviceIcon; tone: "details"; Layout.preferredWidth: 44; Layout.preferredHeight: 44; iconPadding: 7 }
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { Layout.fillWidth: true; text: settingsRoot.label("ملاءمة الجهاز", "Device Fit"); color: theme.text; font.pixelSize: 22; font.bold: true; wrapMode: Text.Wrap }
                    Label { Layout.fillWidth: true; text: settingsRoot.label("اختر توازنًا مبسطًا بين الحمل على الجهاز والتحليل الإضافي. النظام يبقى مسؤولًا عن التطبيق الآمن والرجوع عند الحاجة.", "Choose a simple balance between device load and extra analysis. The system remains responsible for safe application and fallback."); color: theme.muted; font.pixelSize: 13; wrapMode: Text.Wrap }
                }
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.deviceIcon
                tone: settingsRoot.hasDeviceDraftChanges ? "warn" : "info"
                title: settingsRoot.label("الوضع المختار", "Selected mode")
                detail: settingsRoot.deepRuntimeModeTitle(settingsRoot.draftDeepRuntimeMode) + " · " + settingsRoot.deepRuntimeModeDescription(settingsRoot.draftDeepRuntimeMode)
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.compatibilityIcon
                tone: backend.deepRuntimeIsFallback ? "warn" : "success"
                title: settingsRoot.label("الوضع الفعلي", "Effective mode")
                detail: settingsRoot.deepRuntimeModeTitle(backend.deepRuntimeEffectiveMode) + " · " + settingsRoot.safeString(backend.deepRuntimeSelectedBackend, settingsRoot.label("حسب النظام", "System selected"))
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.infoIcon
                tone: settingsRoot.benchmarkReady ? "success" : "neutral"
                title: settingsRoot.label("الوضع المقترح", "Recommended mode")
                detail: settingsRoot.benchmarkReady ? settingsRoot.deepRuntimeModeTitle(backend.deepRuntimeRecommendedMode) : settingsRoot.label("شغّل فحص الجهاز للحصول على اقتراح مناسب.", "Run the device check to get a suitable recommendation.")
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.warningIcon
                tone: backend.deepRuntimeIsFallback ? "warn" : "neutral"
                title: settingsRoot.label("سبب التوافق", "Compatibility reason")
                detail: settingsRoot.userSafeText(backend.deepRuntimeFallbackReasonText, settingsRoot.label("لا توجد تعديلات توافق معروضة حالياً.", "No compatibility adjustment is currently reported."))
            }

            InfoPill {
                textValue: settingsRoot.deviceFeedbackText.length > 0 ? settingsRoot.deviceFeedbackText : settingsRoot.deviceFeedbackFallback()
                pillTone: settingsRoot.deviceFeedbackCurrentTone()
            }
        }
    }

    GlassCard {
        Layout.fillWidth: true
        implicitHeight: deviceModesContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: deviceModesContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                AssetIcon { sourceUrl: settingsRoot.settingsIcon; tone: "info"; Layout.preferredWidth: 44; Layout.preferredHeight: 44; iconPadding: 7 }
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { Layout.fillWidth: true; text: settingsRoot.label("وضع الأداء", "Performance mode"); color: theme.text; font.pixelSize: 22; font.bold: true; wrapMode: Text.Wrap }
                    Label { Layout.fillWidth: true; text: settingsRoot.label("هذه اختيارات مبسطة للاستخدام اليومي. أدوات الاسترجاع والفحص الفنية المتقدمة غير ظاهرة هنا.", "These are simplified choices for everyday use. Advanced recovery and technical analysis tools are not shown here."); color: theme.muted; font.pixelSize: 13; wrapMode: Text.Wrap }
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: settingsRoot.compactLayout ? 1 : 2
                columnSpacing: 12
                rowSpacing: 12

                SelectableInfoCard {
                    titleText: settingsRoot.deepRuntimeModeTitle("auto")
                    descriptionText: settingsRoot.deepRuntimeModeDescription("auto")
                    helpText: settingsRoot.label("مناسب لمعظم الأجهزة لأن النظام يختار حسب الفحص والحالة الحالية.", "Suitable for most devices because the system chooses based on the check and current state.")
                    badgeText: settingsRoot.deepRuntimeModeBadge("auto")
                    accentColor: Ui.roleColor(theme, "info")
                    selected: settingsRoot.draftDeepRuntimeMode === "auto"
                    enabled: !settingsRoot.deviceApplyInFlight && !settingsRoot.deviceBenchmarkInFlight
                    opacity: enabled ? 1.0 : 0.55
                    onChosen: settingsRoot.chooseDraftDeepRuntimeMode("auto")
                }

                SelectableInfoCard {
                    titleText: settingsRoot.deepRuntimeModeTitle("classic")
                    descriptionText: settingsRoot.deepRuntimeModeDescription("classic")
                    helpText: settingsRoot.label("اختره إذا كان الجهاز أضعف أو تريد أقل استهلاك ممكن.", "Choose this for weaker devices or when you want the lowest possible load.")
                    badgeText: settingsRoot.deepRuntimeModeBadge("classic")
                    accentColor: Ui.roleColor(theme, "details")
                    selected: settingsRoot.draftDeepRuntimeMode === "classic"
                    enabled: !settingsRoot.deviceApplyInFlight && !settingsRoot.deviceBenchmarkInFlight
                    opacity: enabled ? 1.0 : 0.55
                    onChosen: settingsRoot.chooseDraftDeepRuntimeMode("classic")
                }

                SelectableInfoCard {
                    titleText: settingsRoot.deepRuntimeModeTitle("hybrid")
                    descriptionText: settingsRoot.deepRuntimeModeDescription("hybrid")
                    helpText: settingsRoot.label("يحتاج موارد أكثر، والتطبيق الفعلي يبقى حسب حالة النظام.", "Uses more resources, and the effective application still depends on system state.")
                    badgeText: settingsRoot.deepRuntimeModeBadge("hybrid")
                    accentColor: Ui.roleColor(theme, "success")
                    selected: settingsRoot.draftDeepRuntimeMode === "hybrid"
                    enabled: !settingsRoot.deviceApplyInFlight && !settingsRoot.deviceBenchmarkInFlight
                    opacity: enabled ? 1.0 : 0.55
                    onChosen: settingsRoot.chooseDraftDeepRuntimeMode("hybrid")
                }

                SelectableInfoCard {
                    titleText: settingsRoot.deepRuntimeModeTitle("hybrid_accelerated")
                    descriptionText: settingsRoot.deepRuntimeModeDescription("hybrid_accelerated")
                    helpText: settingsRoot.label("يستخدم المسار الأسرع فقط إذا كان متاحًا ومدعومًا من النظام.", "Uses the faster path only when available and supported by the system.")
                    badgeText: settingsRoot.deepRuntimeModeBadge("hybrid_accelerated")
                    accentColor: Ui.roleColor(theme, "primary")
                    selected: settingsRoot.draftDeepRuntimeMode === "hybrid_accelerated"
                    enabled: !settingsRoot.deviceApplyInFlight && !settingsRoot.deviceBenchmarkInFlight
                    opacity: enabled ? 1.0 : 0.55
                    onChosen: settingsRoot.chooseDraftDeepRuntimeMode("hybrid_accelerated")
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AppButton {
                    text: settingsRoot.deviceApplyInFlight ? settingsRoot.label("جاري الحفظ…", "Saving…") : settingsRoot.label("حفظ وضع الجهاز", "Save device mode")
                    role: "primary"
                    enabled: settingsRoot.hasDeviceDraftChanges && !settingsRoot.deviceApplyInFlight && !settingsRoot.deviceBenchmarkInFlight && !settingsRoot.settingsActionInFlight
                    onClicked: settingsRoot.applyDeviceSettings()
                }

                AppButton {
                    text: settingsRoot.label("إلغاء", "Discard")
                    role: "neutral"
                    enabled: settingsRoot.hasDeviceDraftChanges && !settingsRoot.deviceApplyInFlight && !settingsRoot.deviceBenchmarkInFlight
                    onClicked: settingsRoot.resetDeviceDrafts()
                }
            }
        }
    }

    GlassCard {
        Layout.fillWidth: true
        implicitHeight: deviceBenchmarkContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: deviceBenchmarkContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                AssetIcon { sourceUrl: settingsRoot.compatibilityIcon; tone: settingsRoot.benchmarkReady ? "success" : "info"; Layout.preferredWidth: 44; Layout.preferredHeight: 44; iconPadding: 7 }
                ColumnLayout {
                    Layout.fillWidth: true
                    Label { Layout.fillWidth: true; text: settingsRoot.label("فحص الجهاز", "Device check"); color: theme.text; font.pixelSize: 22; font.bold: true; wrapMode: Text.Wrap }
                    Label { Layout.fillWidth: true; text: settingsRoot.label("يشغّل فحصًا محليًا قصيرًا لمساعدة BioAuth على اقتراح الوضع الأنسب. لا يبدأ جلسة حماية ولا يغيّر الوضع وحده.", "Runs a short local check to help BioAuth recommend the best fit. It does not start a protected session or change the mode by itself."); color: theme.muted; font.pixelSize: 13; wrapMode: Text.Wrap }
                }
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.compatibilityIcon
                tone: settingsRoot.benchmarkReady ? "success" : "neutral"
                title: settingsRoot.label("آخر فحص", "Last check")
                detail: settingsRoot.benchmarkStatusText()
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.infoIcon
                tone: "info"
                title: settingsRoot.label("الخيار المقترح", "Suggested option")
                detail: settingsRoot.benchmarkReady ? settingsRoot.safeString(settingsRoot.benchmarkState.recommended_backend, settingsRoot.safeString(backend.deepRuntimeSelectedBackend, settingsRoot.label("حسب النظام", "System selected"))) : settingsRoot.label("غير متوفر قبل تشغيل الفحص.", "Unavailable before running a check.")
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AppButton {
                    text: settingsRoot.deviceBenchmarkInFlight ? settingsRoot.label("جاري الفحص…", "Checking…") : (settingsRoot.benchmarkReady ? settingsRoot.label("إعادة فحص الجهاز", "Run check again") : settingsRoot.label("تشغيل فحص الجهاز", "Run device check"))
                    role: "primary"
                    enabled: !settingsRoot.settingsActionInFlight && !settingsRoot.deviceApplyInFlight && !settingsRoot.deviceBenchmarkInFlight
                    onClicked: settingsRoot.runUserDeviceBenchmark()
                }

                AppButton {
                    text: settingsRoot.label("استخدام المقترح", "Use recommendation")
                    role: "neutral"
                    enabled: settingsRoot.benchmarkReady && !settingsRoot.deviceApplyInFlight && !settingsRoot.deviceBenchmarkInFlight
                    onClicked: settingsRoot.useRecommendedDeviceMode()
                }

                AppButton {
                    text: settingsRoot.label("مسح الفحص", "Clear check")
                    role: "neutral"
                    enabled: settingsRoot.benchmarkReady && !settingsRoot.settingsActionInFlight && !settingsRoot.deviceApplyInFlight && !settingsRoot.deviceBenchmarkInFlight
                    onClicked: settingsRoot.clearUserDeviceBenchmark()
                }
            }
        }
    }

    SettingsCompanionMobileCard {
        Layout.fillWidth: true
        Layout.columnSpan: settingsRoot.compactLayout ? 1 : 2
        controller: root
        rootWindow: settingsRoot.rootWindow
        theme: settingsRoot.theme
    }
}
