import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../components"
import "../settings"
import "../../theme/Ui.js" as Ui

GridLayout {
    id: generalSettingsSection
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
    visible: settingsRoot.activeSection === "general"
    enabled: visible
    Layout.preferredHeight: visible ? implicitHeight : 0
    Layout.minimumHeight: visible ? implicitHeight : 0
    Layout.maximumHeight: visible ? 1000000 : 0

    GlassCard {
        Layout.fillWidth: true
        Layout.columnSpan: settingsRoot.compactLayout ? 1 : 2
        implicitHeight: generalHeaderContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: generalHeaderContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AssetIcon {
                    sourceUrl: settingsRoot.preferencesIcon
                    tone: "details"
                    Layout.preferredWidth: 44
                    Layout.preferredHeight: 44
                    iconPadding: 7
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("التفضيلات العامة والتشغيل", "General preferences & startup")
                        color: theme.text
                        font.pixelSize: 22
                        font.bold: true
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("هذه الإعدادات قابلة للتعديل من الواجهة. الحفظ يتم فقط عبر مسار النظام، ولا تعرض الصفحة نجاحاً إلا بعد تحديث القيم المؤكدة.", "These settings are editable from the app. Saving uses the existing system flow, and the page only reports completion after confirmed values refresh.")
                        color: theme.muted
                        font.pixelSize: 13
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }
                }

                InfoPill {
                    textValue: settingsRoot.generalFeedbackText.length > 0 ? settingsRoot.generalFeedbackText : settingsRoot.generalFeedbackFallback()
                    pillTone: settingsRoot.generalFeedbackCurrentTone()
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AppButton {
                    text: settingsRoot.generalApplyInFlight ? settingsRoot.label("جاري الحفظ…", "Saving…") : settingsRoot.label("حفظ التغييرات", "Save changes")
                    role: "success"
                    enabled: settingsRoot.hasGeneralDraftChanges && !settingsRoot.generalApplyInFlight && !settingsRoot.settingsActionInFlight
                    onClicked: settingsRoot.applyGeneralSettings()
                }

                AppButton {
                    text: settingsRoot.label("إلغاء التعديلات", "Discard changes")
                    role: "neutral"
                    enabled: settingsRoot.hasGeneralDraftChanges && !settingsRoot.generalApplyInFlight
                    onClicked: settingsRoot.resetGeneralDrafts()
                }

                Label {
                    Layout.fillWidth: true
                    text: settingsRoot.hasGeneralDraftChanges ? settingsRoot.label("راجع التغييرات ثم احفظها.", "Review changes before saving.") : settingsRoot.label("لا توجد تغييرات معلّقة.", "No pending changes.")
                    color: theme.muted
                    font.pixelSize: 12
                    horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                    wrapMode: Text.Wrap
                }
            }
        }
    }

    GlassCard {
        Layout.fillWidth: true
        Layout.columnSpan: settingsRoot.compactLayout ? 1 : 2
        implicitHeight: interfaceGuideContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: interfaceGuideContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AssetIcon {
                    sourceUrl: settingsRoot.infoIcon
                    tone: "details"
                    Layout.preferredWidth: 44
                    Layout.preferredHeight: 44
                    iconPadding: 7
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("شرح الواجهة", "Interface guide")
                        color: theme.text
                        font.pixelSize: 22
                        font.bold: true
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("أعد عرض جولة التعريف بالتطبيق في أي وقت. هذا لا يغير إعدادات الأمان أو حالة الحساب.", "Replay the app guide at any time. This does not change security settings or account state.")
                        color: theme.muted
                        font.pixelSize: 13
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AppButton {
                    text: settingsRoot.label("إعادة شرح الواجهة", "Replay guide")
                    role: "details"
                    compact: true
                    onClicked: settingsRoot.startInterfaceGuideFromSettings()
                }

                Label {
                    Layout.fillWidth: true
                    text: settingsRoot.label("الميزة تعمل من الواجهة فقط حالياً ولا تعتمد على حفظ دائم لحالة الجولة.", "This is UI-only for now and does not depend on persistent tour state.")
                    color: theme.muted
                    font.pixelSize: 12
                    horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                    wrapMode: Text.Wrap
                }
            }
        }
    }

    GlassCard {
        Layout.fillWidth: true
        implicitHeight: appearanceContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: appearanceContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AssetIcon {
                    sourceUrl: settingsRoot.settingsIcon
                    tone: "info"
                    Layout.preferredWidth: 44
                    Layout.preferredHeight: 44
                    iconPadding: 7
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("المظهر واللغة", "Appearance & language")
                        color: theme.text
                        font.pixelSize: 22
                        font.bold: true
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("اختر الشكل ولغة الواجهة. يتم حفظ الاختيار بعد الضغط على زر الحفظ فقط.", "Choose the visual theme and interface language. Changes are saved only after pressing Save.")
                        color: theme.muted
                        font.pixelSize: 13
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8

                Label {
                    Layout.fillWidth: true
                    text: backend.tr("user_settings_theme_label")
                    color: theme.text
                    font.bold: true
                    horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12

                    ChoiceChip {
                        titleText: settingsRoot.label("داكن", "Dark")
                        descriptionText: settingsRoot.label("مظهر داكن وهادئ مناسب للحماية اليومية.", "A calm dark appearance for everyday protection.")
                        selected: settingsRoot.draftTheme === "dark"
                        accentColor: Ui.roleColor(theme, "success")
                        enabled: !settingsRoot.generalApplyInFlight
                        opacity: enabled ? 1.0 : 0.55
                        onChosen: settingsRoot.chooseDraftTheme("dark")
                    }

                    ChoiceChip {
                        titleText: settingsRoot.label("فاتح", "Light")
                        descriptionText: settingsRoot.label("مظهر فاتح بقراءة واضحة.", "A light appearance with clear readability.")
                        selected: settingsRoot.draftTheme === "light"
                        accentColor: Ui.roleColor(theme, "info")
                        enabled: !settingsRoot.generalApplyInFlight
                        opacity: enabled ? 1.0 : 0.55
                        onChosen: settingsRoot.chooseDraftTheme("light")
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 8

                Label {
                    Layout.fillWidth: true
                    text: backend.tr("user_settings_language_label")
                    color: theme.text
                    font.bold: true
                    horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 12

                    ChoiceChip {
                        titleText: "العربية"
                        descriptionText: settingsRoot.label("واجهة عربية باتجاه مناسب للنصوص.", "Arabic interface with appropriate text direction.")
                        selected: settingsRoot.draftLanguage === "ar"
                        accentColor: Ui.roleColor(theme, "details")
                        enabled: !settingsRoot.generalApplyInFlight
                        opacity: enabled ? 1.0 : 0.55
                        onChosen: settingsRoot.chooseDraftLanguage("ar")
                    }

                    ChoiceChip {
                        titleText: "English"
                        descriptionText: settingsRoot.label("واجهة إنجليزية واضحة.", "Clear English interface.")
                        selected: settingsRoot.draftLanguage === "en"
                        accentColor: Ui.roleColor(theme, "info")
                        enabled: !settingsRoot.generalApplyInFlight
                        opacity: enabled ? 1.0 : 0.55
                        onChosen: settingsRoot.chooseDraftLanguage("en")
                    }
                }
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.infoIcon
                tone: settingsRoot.hasGeneralDraftChanges ? "warn" : "success"
                title: settingsRoot.label("القيم الحالية", "Current values")
                detail: settingsRoot.label("النظام الآن", "System now") + ": " + settingsRoot.themeLabel(backend.themeMode) + " / " + settingsRoot.languageLabel(backend.language)
                trailingText: settingsRoot.label("المسودة", "Draft") + ": " + settingsRoot.themeLabel(settingsRoot.draftTheme) + " / " + settingsRoot.languageLabel(settingsRoot.draftLanguage)
            }
        }
    }

    GlassCard {
        Layout.fillWidth: true
        implicitHeight: interactionContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: interactionContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AssetIcon {
                    sourceUrl: settingsRoot.infoIcon
                    tone: "success"
                    Layout.preferredWidth: 44
                    Layout.preferredHeight: 44
                    iconPadding: 7
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("التفاعل اليومي", "Daily interaction")
                        color: theme.text
                        font.pixelSize: 22
                        font.bold: true
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("تحكم بأصوات الأزرار بدون التأثير على تنبيهات الأمان أو قرارات الحماية.", "Control button sounds without changing security alerts or protection decisions.")
                        color: theme.muted
                        font.pixelSize: 13
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: buttonSoundsDraftRow.implicitHeight + 24
                radius: 18
                color: settingsRoot.draftButtonSoundsMuted ? Ui.colorToken(theme, "dangerBg") : Ui.colorToken(theme, "surface1")
                border.color: settingsRoot.draftButtonSoundsMuted ? Ui.roleColor(theme, "warn") : Ui.colorToken(theme, "border")
                border.width: 1

                RowLayout {
                    id: buttonSoundsDraftRow
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 12

                    StartupSwitch {
                        theme: settingsRoot.calmToggleTheme
                        checked: !settingsRoot.draftButtonSoundsMuted
                        enabled: !settingsRoot.generalApplyInFlight
                        onToggled: function(nextChecked) {
                            settingsRoot.setDraftButtonSoundsMuted(!nextChecked)
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4

                        Label {
                            Layout.fillWidth: true
                            text: settingsRoot.label("أصوات الأزرار", "Button sounds")
                            color: theme.text
                            font.bold: true
                            horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                            wrapMode: Text.Wrap
                        }

                        Label {
                            Layout.fillWidth: true
                            text: settingsRoot.draftButtonSoundsMuted ? settingsRoot.label("سيتم كتم أصوات الأزرار وأصوات تنبيه ويندوز الناتجة عن ضغطات الواجهة بعد الحفظ.", "Button sounds and Windows click feedback will be muted after saving.") : settingsRoot.label("ستبقى أصوات الأزرار مفعّلة بعد الحفظ.", "Button sounds will remain enabled after saving.")
                            color: theme.muted
                            horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                            wrapMode: Text.Wrap
                        }
                    }

                    InfoPill {
                        textValue: settingsRoot.buttonSoundsLabel(settingsRoot.draftButtonSoundsMuted)
                        pillTone: settingsRoot.draftButtonSoundsMuted ? "warn" : "success"
                    }
                }
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.infoIcon
                tone: backend.buttonSoundsMuted ? "neutral" : "success"
                title: settingsRoot.label("الحالة المؤكدة", "Confirmed state")
                detail: settingsRoot.buttonSoundsLabel(backend.buttonSoundsMuted)
            }
        }
    }

    GlassCard {
        Layout.fillWidth: true
        implicitHeight: startupContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: startupContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AssetIcon {
                    sourceUrl: settingsRoot.compatibilityIcon
                    tone: "details"
                    Layout.preferredWidth: 44
                    Layout.preferredHeight: 44
                    iconPadding: 7
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("التشغيل وتذكر الدخول", "Startup & remembered sign-in")
                        color: theme.text
                        font.pixelSize: 22
                        font.bold: true
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("التشغيل مع النظام وتذكر الدخول يتم حفظهما عبر النظام. عند تشغيل التطبيق تلقائياً، سيبقي النظام تذكر الدخول مفعلاً إذا كان ذلك مطلوباً.", "Startup and remembered sign-in are saved through BioAuth. When startup is enabled, the system may keep remembered sign-in enabled if required.")
                        color: theme.muted
                        font.pixelSize: 13
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: startupDraftRow.implicitHeight + 24
                radius: 18
                color: Ui.colorToken(theme, "surface1")
                border.color: settingsRoot.draftRunOnStartup ? Ui.roleColor(theme, "success") : Ui.colorToken(theme, "border")
                border.width: 1

                RowLayout {
                    id: startupDraftRow
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 12

                    StartupSwitch {
                        theme: settingsRoot.calmToggleTheme
                        checked: settingsRoot.draftRunOnStartup
                        enabled: !settingsRoot.generalApplyInFlight
                        onToggled: function(nextChecked) {
                            settingsRoot.setDraftStartupEnabled(nextChecked)
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4

                        Label {
                            Layout.fillWidth: true
                            text: backend.tr("user_settings_startup_label")
                            color: theme.text
                            font.bold: true
                            horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                            wrapMode: Text.Wrap
                        }

                        Label {
                            Layout.fillWidth: true
                            text: settingsRoot.draftRunOnStartup ? settingsRoot.label("سيُطلب من النظام تشغيل BioAuth مع بدء التشغيل بعد الحفظ.", "BioAuth will request launch on system startup after saving.") : settingsRoot.label("لن يطلب BioAuth التشغيل التلقائي بعد الحفظ.", "BioAuth will not request automatic startup after saving.")
                            color: theme.muted
                            horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                            wrapMode: Text.Wrap
                        }
                    }

                    InfoPill {
                        textValue: settingsRoot.draftRunOnStartup ? backend.tr("enabled") : backend.tr("disabled")
                        pillTone: settingsRoot.draftRunOnStartup ? "success" : "neutral"
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: rememberDraftRow.implicitHeight + 24
                radius: 18
                color: Ui.colorToken(theme, "surface1")
                border.color: settingsRoot.draftRememberLoginEnabled ? Ui.roleColor(theme, "success") : Ui.colorToken(theme, "border")
                border.width: 1

                RowLayout {
                    id: rememberDraftRow
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 12

                    StartupSwitch {
                        theme: settingsRoot.calmToggleTheme
                        checked: settingsRoot.draftRememberLoginEnabled
                        enabled: !settingsRoot.generalApplyInFlight
                        onToggled: function(nextChecked) {
                            settingsRoot.setDraftRememberLoginEnabled(nextChecked)
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4

                        Label {
                            Layout.fillWidth: true
                            text: settingsRoot.label("تذكر تسجيل الدخول", "Remember login")
                            color: theme.text
                            font.bold: true
                            horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                            wrapMode: Text.Wrap
                        }

                        Label {
                            Layout.fillWidth: true
                            text: settingsRoot.draftRememberLoginEnabled ? settingsRoot.label("سيحفظ النظام حالة تذكر الدخول حسب سياسة BioAuth.", "The system will keep remembered sign-in according to BioAuth policy.") : settingsRoot.label("سيتم إيقاف تذكر الدخول، وسيتم إيقاف التشغيل التلقائي في المسودة لتجنب حالة متعارضة.", "Remembered sign-in will turn off, and startup is disabled in the draft to avoid a conflicting state.")
                            color: theme.muted
                            horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                            wrapMode: Text.Wrap
                        }
                    }

                    InfoPill {
                        textValue: settingsRoot.draftRememberLoginEnabled ? backend.tr("enabled") : backend.tr("disabled")
                        pillTone: settingsRoot.draftRememberLoginEnabled ? "success" : "neutral"
                    }
                }
            }
        }
    }

    GlassCard {
        Layout.fillWidth: true
        implicitHeight: confirmedGeneralContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: confirmedGeneralContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AssetIcon {
                    sourceUrl: settingsRoot.storageIcon
                    tone: "info"
                    Layout.preferredWidth: 44
                    Layout.preferredHeight: 44
                    iconPadding: 7
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("الحالة المؤكدة من النظام", "System-confirmed state")
                        color: theme.text
                        font.pixelSize: 22
                        font.bold: true
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("هذا الملخص يعرض القيم التي أكدها النظام، وليس مجرد المسودة المحلية.", "This summary shows values confirmed by the system, not only the local draft.")
                        color: theme.muted
                        font.pixelSize: 13
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }
                }
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.settingsIcon
                tone: backend.themeMode === settingsRoot.draftTheme ? "success" : "warn"
                title: backend.tr("user_settings_theme_label")
                detail: settingsRoot.label("مؤكد", "Confirmed") + ": " + settingsRoot.themeLabel(backend.themeMode)
                trailingText: settingsRoot.label("مسودة", "Draft") + ": " + settingsRoot.themeLabel(settingsRoot.draftTheme)
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.settingsIcon
                tone: backend.language === settingsRoot.draftLanguage ? "success" : "warn"
                title: backend.tr("user_settings_language_label")
                detail: settingsRoot.label("مؤكد", "Confirmed") + ": " + settingsRoot.languageLabel(backend.language)
                trailingText: settingsRoot.label("مسودة", "Draft") + ": " + settingsRoot.languageLabel(settingsRoot.draftLanguage)
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.compatibilityIcon
                tone: backend.runOnStartup === settingsRoot.draftRunOnStartup ? "success" : "warn"
                title: backend.tr("user_settings_startup_label")
                detail: settingsRoot.label("مؤكد", "Confirmed") + ": " + settingsRoot.yesNo(backend.runOnStartup)
                trailingText: settingsRoot.label("مسودة", "Draft") + ": " + settingsRoot.yesNo(settingsRoot.draftRunOnStartup)
            }

            StatusInfoRow {
                Layout.fillWidth: true
                iconSource: settingsRoot.securityIcon
                tone: backend.rememberLoginEnabled === settingsRoot.draftRememberLoginEnabled ? "success" : "warn"
                title: settingsRoot.label("تذكر تسجيل الدخول", "Remember login")
                detail: settingsRoot.label("مؤكد", "Confirmed") + ": " + settingsRoot.yesNo(backend.rememberLoginEnabled)
                trailingText: settingsRoot.label("مسودة", "Draft") + ": " + settingsRoot.yesNo(settingsRoot.draftRememberLoginEnabled)
            }
        }
    }

    GlassCard {
        Layout.fillWidth: true
        Layout.columnSpan: settingsRoot.compactLayout ? 1 : 2
        implicitHeight: aboutContent.implicitHeight + 36
        Layout.minimumHeight: implicitHeight

        ColumnLayout {
            id: aboutContent
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                AssetIcon {
                    sourceUrl: settingsRoot.infoIcon
                    tone: "details"
                    Layout.preferredWidth: 44
                    Layout.preferredHeight: 44
                    iconPadding: 7
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 4

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("حول BioAuth", "About BioAuth")
                        color: theme.text
                        font.pixelSize: 22
                        font.bold: true
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }

                    Label {
                        Layout.fillWidth: true
                        text: settingsRoot.label("معلومات التطبيق والدعم متاحة من هنا بدون فتح العرض المتقدم.", "App information and support details are available here without opening the advanced view.")
                        color: theme.muted
                        font.pixelSize: 13
                        horizontalAlignment: settingsRoot.isArabic ? Text.AlignRight : Text.AlignLeft
                        wrapMode: Text.Wrap
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                StatusInfoRow {
                    Layout.fillWidth: true
                    iconSource: settingsRoot.infoIcon
                    tone: "neutral"
                    title: settingsRoot.label("الإصدار الحالي", "Current version")
                    detail: settingsRoot.safeString(backend.appVersion || settingsRoot.updateState.currentVersion, settingsRoot.label("غير متوفر", "Unavailable"))
                }

                AppButton {
                    text: settingsRoot.label("فتح About Us", "Open About Us")
                    role: "details"
                    compact: true
                    enabled: !settingsRoot.settingsActionInFlight
                    onClicked: settingsRoot.openAboutUs()
                }
            }
        }
    }
}
