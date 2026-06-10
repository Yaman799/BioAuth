import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

Item {
    id: root
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property bool compactLayout: rootWindow ? rootWindow.denseWidth : width < 980
    property real contentWidth: Math.min((rootWindow ? rootWindow.width : width) - 24, 1220)
    property real indicatorSize: rootWindow ? rootWindow.scaled(194, 136, 194) : 180
    property bool forgotUsernameExpanded: false
    property string forgotUsernameFeedback: ""
    property string forgotUsernameFeedbackTone: "info"
    property bool forgotUsernameRevealExpanded: false
    property string forgotUsernameRevealFeedback: ""
    property string forgotUsernameRevealFeedbackTone: "info"
    property bool forgotPasswordExpanded: false
    property string forgotPasswordFeedback: ""
    property string forgotPasswordFeedbackTone: "info"
    property bool forgotPasswordResetExpanded: false
    property string forgotPasswordResetFeedback: ""
    property string forgotPasswordResetFeedbackTone: "info"

    function trx(arText, enText) { return rootWindow ? rootWindow.trx(arText, enText) : enText }
    function resetForgotUsernameFlow(clearEmail) {
        forgotUsernameFeedback = ""
        forgotUsernameFeedbackTone = "info"
        forgotUsernameRevealExpanded = false
        forgotUsernameRevealFeedback = ""
        forgotUsernameRevealFeedbackTone = "info"
        if (forgotUsernamePassword)
            forgotUsernamePassword.text = ""
        if (clearEmail && forgotUsernameEmail)
            forgotUsernameEmail.text = ""
    }
    function resetForgotPasswordFlow(clearFields) {
        forgotPasswordFeedback = ""
        forgotPasswordFeedbackTone = "info"
        forgotPasswordResetExpanded = false
        forgotPasswordResetFeedback = ""
        forgotPasswordResetFeedbackTone = "info"
        if (forgotPasswordNewPassword)
            forgotPasswordNewPassword.text = ""
        if (forgotPasswordConfirmPassword)
            forgotPasswordConfirmPassword.text = ""
        if (clearFields) {
            if (forgotPasswordIdentifier)
                forgotPasswordIdentifier.text = ""
            if (forgotPasswordRecoveryCode)
                forgotPasswordRecoveryCode.text = ""
        }
    }
    anchors.fill: parent

    Connections {
        target: backend
        function onForgotUsernameLookupResult(message, tone) {
            root.forgotUsernameFeedback = message || ""
            root.forgotUsernameFeedbackTone = tone || "info"
            if ((tone || "info") !== "success") {
                root.forgotUsernameRevealExpanded = false
                root.forgotUsernameRevealFeedback = ""
                root.forgotUsernameRevealFeedbackTone = "info"
                if (forgotUsernamePassword)
                    forgotUsernamePassword.text = ""
            }
        }

        function onForgotUsernameRevealResult(message, tone) {
            root.forgotUsernameRevealFeedback = message || ""
            root.forgotUsernameRevealFeedbackTone = tone || "info"
        }

        function onForgotPasswordVerificationResult(message, tone) {
            root.forgotPasswordFeedback = message || ""
            root.forgotPasswordFeedbackTone = tone || "info"
            if ((tone || "info") === "success") {
                root.forgotPasswordResetExpanded = true
                root.forgotPasswordResetFeedback = ""
                root.forgotPasswordResetFeedbackTone = "info"
                if (forgotPasswordNewPassword)
                    forgotPasswordNewPassword.forceActiveFocus()
            } else {
                root.forgotPasswordResetExpanded = false
                root.forgotPasswordResetFeedback = ""
                root.forgotPasswordResetFeedbackTone = "info"
                if (forgotPasswordNewPassword)
                    forgotPasswordNewPassword.text = ""
                if (forgotPasswordConfirmPassword)
                    forgotPasswordConfirmPassword.text = ""
            }
        }

        function onForgotPasswordResetResult(message, tone) {
            root.forgotPasswordResetFeedback = message || ""
            root.forgotPasswordResetFeedbackTone = tone || "info"
            if ((tone || "info") === "success") {
                root.forgotPasswordExpanded = false
                root.resetForgotPasswordFlow(true)
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        color: theme.window || "#020913"

        Rectangle {
            anchors.fill: parent
            color: "transparent"
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(0.03, 0.14, 0.22, 0.92) }
                GradientStop { position: 0.48; color: Qt.rgba(0.02, 0.07, 0.13, 1.0) }
                GradientStop { position: 1.0; color: Qt.rgba(0.01, 0.03, 0.08, 1.0) }
            }
        }
    }

    Item {
        anchors.fill: parent
        clip: true

        Rectangle {
            width: Math.max(parent.width, parent.height) * 0.74
            height: width
            radius: width / 2
            x: -width * 0.36
            y: -height * 0.22
            color: Qt.rgba(0.05, 0.55, 0.70, 0.10)
            border.color: Qt.rgba(0.13, 0.83, 0.93, 0.10)
            border.width: 1
        }

        Rectangle {
            width: Math.max(parent.width, parent.height) * 0.60
            height: width
            radius: width / 2
            x: parent.width - width * 0.28
            y: parent.height - height * 0.45
            color: Qt.rgba(0.00, 0.72, 0.63, 0.075)
            border.color: Qt.rgba(0.18, 0.83, 0.75, 0.07)
            border.width: 1
        }

        Repeater {
            model: 7
            Rectangle {
                width: parent.width * (index % 2 === 0 ? 0.36 : 0.24)
                height: 1
                x: index % 2 === 0 ? 18 : parent.width - width - 18
                y: parent.height * (0.13 + index * 0.105)
                color: index % 2 === 0 ? theme.accent : theme.success
                opacity: 0.055
            }
        }
    }


    ScrollView {
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        Item {
            width: Math.min(parent.width, root.contentWidth)
            x: Math.max(0, (parent.width - width) / 2)
            implicitHeight: authColumn.implicitHeight + 24

            ColumnLayout {
                id: authColumn
                width: parent.width
                spacing: root.compactLayout ? 16 : 24

                Item {
                    id: authHero
                    Layout.fillWidth: true
                    implicitHeight: root.compactLayout ? 232 : 332
                    clip: false

                    Rectangle {
                        anchors.centerIn: parent
                        width: Math.min(parent.width * 0.72, root.compactLayout ? 520 : 760)
                        height: width
                        radius: width / 2
                        color: Qt.rgba(0.00, 0.82, 0.86, 0.035)
                        border.color: Qt.rgba(0.13, 0.83, 0.93, 0.16)
                        border.width: 1
                    }

                    Rectangle {
                        anchors.centerIn: parent
                        width: Math.min(parent.width * 0.52, root.compactLayout ? 390 : 560)
                        height: width
                        radius: width / 2
                        color: "transparent"
                        border.color: Qt.rgba(0.18, 0.83, 0.75, 0.18)
                        border.width: 1
                    }

                    Image {
                        id: heroBrandImage
                        anchors.centerIn: parent
                        width: Math.min(parent.width * (root.compactLayout ? 1.02 : 0.88), root.compactLayout ? 660 : 1010)
                        height: parent.height * (root.compactLayout ? 1.18 : 1.08)
                        source: Qt.resolvedUrl("assets/brand/bioauth_login_hero.png")
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        mipmap: true
                        asynchronous: true
                        opacity: 0.98
                    }

                    Label {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: root.compactLayout ? 0 : 4
                        width: Math.min(parent.width - 36, 760)
                        text: backend.tr("auth_subtitle")
                        color: theme.muted
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        font.pixelSize: root.compactLayout ? 12 : 13
                        opacity: 0.86
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: root.compactLayout ? 1 : 2
                    columnSpacing: 22
                    rowSpacing: 22

                    GlassCard {
                        Layout.fillWidth: true
                        implicitHeight: loginColumn.implicitHeight + 56
                        border.color: Qt.rgba(0.13, 0.83, 0.93, 0.56)
                        color: Qt.rgba(0.03, 0.10, 0.17, 0.82)

                        ColumnLayout {
                            id: loginColumn
                            anchors.fill: parent
                            anchors.margins: root.compactLayout ? 20 : 28
                            spacing: 0

                            Label {
                                text: backend.tr("signin")
                                color: theme.text
                                font.pixelSize: root.compactLayout ? 24 : 28
                                font.bold: true
                            }

                            Label {
                                Layout.topMargin: 10
                                text: trx("ادخل للوصول إلى لوحة التحكم الأمنية الحية.", "Sign in to enter the live security console.")
                                color: theme.muted
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }

                            AppTextField {
                                id: loginUsername
                                Layout.topMargin: 18
                                Layout.fillWidth: true
                                placeholderText: backend.tr("username")
                            }

                            AppTextField {
                                id: loginPassword
                                Layout.topMargin: 14
                                Layout.fillWidth: true
                                placeholderText: backend.tr("password")
                                echoMode: TextInput.Password
                            }

                            RowLayout {
                                Layout.topMargin: 12
                                Layout.fillWidth: true
                                spacing: 12

                                StartupSwitch {
                                    checked: backend.rememberLoginEnabled
                                    onToggled: backend.setRememberLoginEnabled(checked)
                                }

                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    Label {
                                        text: backend.tr("remember_login")
                                        color: theme.text
                                        wrapMode: Text.Wrap
                                    }
                                    Label {
                                        text: backend.tr("remember_login_note")
                                        color: theme.muted
                                        wrapMode: Text.Wrap
                                        font.pixelSize: 12
                                    }
                                }
                            }

                            AppButton {
                                text: backend.tr("sign_in")
                                role: "primary"
                                Layout.topMargin: 22
                                Layout.fillWidth: true
                                onClicked: backend.signIn(loginUsername.text, loginPassword.text)
                            }

                            Item {
                                Layout.topMargin: 14
                                Layout.fillWidth: true
                                implicitHeight: forgotUsernameLink.implicitHeight

                                Label {
                                    id: forgotUsernameLink
                                    text: backend.tr("forgot_username")
                                    color: theme.accent
                                    font.pixelSize: 13
                                    font.underline: forgotUsernameLinkArea.containsMouse
                                }

                                MouseArea {
                                    id: forgotUsernameLinkArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        root.forgotUsernameExpanded = !root.forgotUsernameExpanded
                                        root.resetForgotUsernameFlow(!root.forgotUsernameExpanded)
                                        if (root.forgotUsernameExpanded) {
                                            root.forgotPasswordExpanded = false
                                            root.resetForgotPasswordFlow(true)
                                            forgotUsernameEmail.forceActiveFocus()
                                        }
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.topMargin: 10
                                Layout.fillWidth: true
                                visible: root.forgotUsernameExpanded
                                spacing: 0

                                Label {
                                    Layout.fillWidth: true
                                    text: backend.tr("forgot_username_help")
                                    color: theme.muted
                                    wrapMode: Text.Wrap
                                }

                                AppTextField {
                                    id: forgotUsernameEmail
                                    Layout.topMargin: 12
                                    Layout.fillWidth: true
                                    placeholderText: backend.tr("forgot_username_email_placeholder")
                                    onTextEdited: root.resetForgotUsernameFlow(false)
                                    onAccepted: backend.requestUsernameHint(text)
                                }

                                Label {
                                    Layout.topMargin: 8
                                    Layout.fillWidth: true
                                    text: backend.tr("forgot_username_email_help")
                                    color: theme.muted
                                    wrapMode: Text.Wrap
                                    font.pixelSize: 12
                                }

                                RowLayout {
                                    Layout.topMargin: 12
                                    Layout.fillWidth: true
                                    spacing: 10

                                    AppButton {
                                        text: backend.tr("forgot_username_lookup")
                                        role: "details"
                                        Layout.fillWidth: true
                                        ToolTip.visible: hovered
                                        ToolTip.text: backend.tr("forgot_username_lookup_tooltip")
                                        ToolTip.delay: 100
                                        onClicked: backend.requestUsernameHint(forgotUsernameEmail.text)
                                    }

                                    AppButton {
                                        text: backend.tr("forgot_username_cancel")
                                        role: "neutral"
                                        compact: true
                                        onClicked: {
                                            root.forgotUsernameExpanded = false
                                            root.resetForgotUsernameFlow(true)
                                        }
                                    }
                                }

                                Label {
                                    Layout.topMargin: 12
                                    Layout.fillWidth: true
                                    visible: root.forgotUsernameFeedback.length > 0
                                    text: root.forgotUsernameFeedback
                                    color: rootWindow ? rootWindow.toneColor(root.forgotUsernameFeedbackTone) : theme.info
                                    wrapMode: Text.Wrap
                                }

                                Label {
                                    Layout.topMargin: 8
                                    Layout.fillWidth: true
                                    text: backend.tr("forgot_username_privacy_note")
                                    color: theme.muted
                                    wrapMode: Text.Wrap
                                    font.pixelSize: 12
                                }

                                ColumnLayout {
                                    Layout.topMargin: 12
                                    Layout.fillWidth: true
                                    visible: root.forgotUsernameFeedbackTone === "success"
                                    spacing: 0

                                    AppButton {
                                        text: backend.tr("forgot_username_reveal")
                                        role: "details"
                                        Layout.fillWidth: true
                                        ToolTip.visible: hovered
                                        ToolTip.text: backend.tr("forgot_username_reveal_tooltip")
                                        ToolTip.delay: 100
                                        onClicked: {
                                            root.forgotUsernameRevealExpanded = !root.forgotUsernameRevealExpanded
                                            root.forgotUsernameRevealFeedback = ""
                                            root.forgotUsernameRevealFeedbackTone = "info"
                                            if (root.forgotUsernameRevealExpanded && forgotUsernamePassword)
                                                forgotUsernamePassword.forceActiveFocus()
                                        }
                                    }

                                    ColumnLayout {
                                        Layout.topMargin: 10
                                        Layout.fillWidth: true
                                        visible: root.forgotUsernameRevealExpanded
                                        spacing: 0

                                        Label {
                                            Layout.fillWidth: true
                                            text: backend.tr("forgot_username_reveal_help")
                                            color: theme.muted
                                            wrapMode: Text.Wrap
                                        }

                                        AppTextField {
                                            id: forgotUsernamePassword
                                            Layout.topMargin: 12
                                            Layout.fillWidth: true
                                            placeholderText: backend.tr("forgot_username_password_placeholder")
                                            echoMode: TextInput.Password
                                            onTextEdited: {
                                                root.forgotUsernameRevealFeedback = ""
                                                root.forgotUsernameRevealFeedbackTone = "info"
                                            }
                                            onAccepted: backend.requestUsernameReveal(forgotUsernameEmail.text, text)
                                        }

                                        Label {
                                            Layout.topMargin: 8
                                            Layout.fillWidth: true
                                            text: backend.tr("forgot_username_password_help")
                                            color: theme.muted
                                            wrapMode: Text.Wrap
                                            font.pixelSize: 12
                                        }

                                        RowLayout {
                                            Layout.topMargin: 12
                                            Layout.fillWidth: true
                                            spacing: 10

                                            AppButton {
                                                text: backend.tr("forgot_username_reveal_action")
                                                role: "info"
                                                Layout.fillWidth: true
                                                ToolTip.visible: hovered
                                                ToolTip.text: backend.tr("forgot_username_reveal_tooltip")
                                                ToolTip.delay: 100
                                                onClicked: backend.requestUsernameReveal(forgotUsernameEmail.text, forgotUsernamePassword.text)
                                            }

                                            AppButton {
                                                text: backend.tr("forgot_username_cancel")
                                                role: "neutral"
                                                compact: true
                                                onClicked: {
                                                    root.forgotUsernameRevealExpanded = false
                                                    root.forgotUsernameRevealFeedback = ""
                                                    root.forgotUsernameRevealFeedbackTone = "info"
                                                    forgotUsernamePassword.text = ""
                                                }
                                            }
                                        }

                                        Label {
                                            Layout.topMargin: 12
                                            Layout.fillWidth: true
                                            visible: root.forgotUsernameRevealFeedback.length > 0
                                            text: root.forgotUsernameRevealFeedback
                                            color: rootWindow ? rootWindow.toneColor(root.forgotUsernameRevealFeedbackTone) : theme.info
                                            wrapMode: Text.Wrap
                                        }
                                    }
                                }
                            }

                            Item {
                                Layout.topMargin: 10
                                Layout.fillWidth: true
                                implicitHeight: forgotPasswordLink.implicitHeight

                                Label {
                                    id: forgotPasswordLink
                                    text: backend.tr("forgot_password")
                                    color: theme.accent
                                    font.pixelSize: 13
                                    font.underline: forgotPasswordLinkArea.containsMouse
                                }

                                MouseArea {
                                    id: forgotPasswordLinkArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        root.forgotPasswordExpanded = !root.forgotPasswordExpanded
                                        root.resetForgotPasswordFlow(!root.forgotPasswordExpanded)
                                        if (root.forgotPasswordExpanded) {
                                            root.forgotUsernameExpanded = false
                                            root.resetForgotUsernameFlow(true)
                                            forgotPasswordIdentifier.forceActiveFocus()
                                        }
                                    }
                                }
                            }

                            ColumnLayout {
                                Layout.topMargin: 10
                                Layout.fillWidth: true
                                visible: root.forgotPasswordExpanded
                                spacing: 0

                                Label {
                                    Layout.fillWidth: true
                                    text: backend.tr("forgot_password_help")
                                    color: theme.muted
                                    wrapMode: Text.Wrap
                                }

                                AppTextField {
                                    id: forgotPasswordIdentifier
                                    Layout.topMargin: 12
                                    Layout.fillWidth: true
                                    placeholderText: backend.tr("forgot_password_identifier_placeholder")
                                    onTextEdited: root.resetForgotPasswordFlow(false)
                                }

                                Label {
                                    Layout.topMargin: 8
                                    Layout.fillWidth: true
                                    text: backend.tr("forgot_password_identifier_help")
                                    color: theme.muted
                                    wrapMode: Text.Wrap
                                    font.pixelSize: 12
                                }

                                AppTextField {
                                    id: forgotPasswordRecoveryCode
                                    Layout.topMargin: 12
                                    Layout.fillWidth: true
                                    placeholderText: backend.tr("forgot_password_recovery_placeholder")
                                    onTextEdited: root.resetForgotPasswordFlow(false)
                                    onAccepted: backend.requestPasswordResetVerification(forgotPasswordIdentifier.text, text)
                                }

                                Label {
                                    Layout.topMargin: 8
                                    Layout.fillWidth: true
                                    text: backend.tr("forgot_password_recovery_help")
                                    color: theme.muted
                                    wrapMode: Text.Wrap
                                    font.pixelSize: 12
                                }

                                RowLayout {
                                    Layout.topMargin: 12
                                    Layout.fillWidth: true
                                    spacing: 10

                                    AppButton {
                                        text: backend.tr("forgot_password_verify")
                                        role: "details"
                                        Layout.fillWidth: true
                                        ToolTip.visible: hovered
                                        ToolTip.text: backend.tr("forgot_password_verify_tooltip")
                                        ToolTip.delay: 100
                                        onClicked: backend.requestPasswordResetVerification(forgotPasswordIdentifier.text, forgotPasswordRecoveryCode.text)
                                    }

                                    AppButton {
                                        text: backend.tr("forgot_username_cancel")
                                        role: "neutral"
                                        compact: true
                                        onClicked: {
                                            root.forgotPasswordExpanded = false
                                            root.resetForgotPasswordFlow(true)
                                        }
                                    }
                                }

                                Label {
                                    Layout.topMargin: 12
                                    Layout.fillWidth: true
                                    visible: root.forgotPasswordFeedback.length > 0
                                    text: root.forgotPasswordFeedback
                                    color: rootWindow ? rootWindow.toneColor(root.forgotPasswordFeedbackTone) : theme.info
                                    wrapMode: Text.Wrap
                                }

                                Label {
                                    Layout.topMargin: 8
                                    Layout.fillWidth: true
                                    text: backend.tr("forgot_password_privacy_note")
                                    color: theme.muted
                                    wrapMode: Text.Wrap
                                    font.pixelSize: 12
                                }

                                ColumnLayout {
                                    Layout.topMargin: 12
                                    Layout.fillWidth: true
                                    visible: root.forgotPasswordResetExpanded
                                    spacing: 0

                                    Label {
                                        Layout.fillWidth: true
                                        text: backend.tr("forgot_password_reset_help")
                                        color: theme.muted
                                        wrapMode: Text.Wrap
                                    }

                                    AppTextField {
                                        id: forgotPasswordNewPassword
                                        Layout.topMargin: 12
                                        Layout.fillWidth: true
                                        placeholderText: backend.tr("new_password")
                                        echoMode: TextInput.Password
                                        onTextEdited: {
                                            root.forgotPasswordResetFeedback = ""
                                            root.forgotPasswordResetFeedbackTone = "info"
                                        }
                                    }

                                    AppTextField {
                                        id: forgotPasswordConfirmPassword
                                        Layout.topMargin: 12
                                        Layout.fillWidth: true
                                        placeholderText: backend.tr("confirm_password")
                                        echoMode: TextInput.Password
                                        onTextEdited: {
                                            root.forgotPasswordResetFeedback = ""
                                            root.forgotPasswordResetFeedbackTone = "info"
                                        }
                                        onAccepted: backend.resetPasswordWithRecoveryCode(forgotPasswordIdentifier.text, forgotPasswordRecoveryCode.text, forgotPasswordNewPassword.text, text)
                                    }

                                    RowLayout {
                                        Layout.topMargin: 12
                                        Layout.fillWidth: true
                                        spacing: 10

                                        AppButton {
                                            text: backend.tr("forgot_password_reset_action")
                                            role: "info"
                                            Layout.fillWidth: true
                                            ToolTip.visible: hovered
                                            ToolTip.text: backend.tr("forgot_password_reset_tooltip")
                                            ToolTip.delay: 100
                                            onClicked: backend.resetPasswordWithRecoveryCode(forgotPasswordIdentifier.text, forgotPasswordRecoveryCode.text, forgotPasswordNewPassword.text, forgotPasswordConfirmPassword.text)
                                        }

                                        AppButton {
                                            text: backend.tr("forgot_username_cancel")
                                            role: "neutral"
                                            compact: true
                                            onClicked: {
                                                root.forgotPasswordResetExpanded = false
                                                root.forgotPasswordResetFeedback = ""
                                                root.forgotPasswordResetFeedbackTone = "info"
                                                if (forgotPasswordNewPassword)
                                                    forgotPasswordNewPassword.text = ""
                                                if (forgotPasswordConfirmPassword)
                                                    forgotPasswordConfirmPassword.text = ""
                                            }
                                        }
                                    }

                                    Label {
                                        Layout.topMargin: 12
                                        Layout.fillWidth: true
                                        visible: root.forgotPasswordResetFeedback.length > 0
                                        text: root.forgotPasswordResetFeedback
                                        color: rootWindow ? rootWindow.toneColor(root.forgotPasswordResetFeedbackTone) : theme.info
                                        wrapMode: Text.Wrap
                                    }
                                }
                            }

                        }
                    }

                    GlassCard {
                        Layout.fillWidth: true
                        implicitHeight: signupColumn.implicitHeight + 56
                        border.color: Qt.rgba(0.18, 0.83, 0.75, 0.34)
                        color: Qt.rgba(0.03, 0.10, 0.17, 0.72)

                        ColumnLayout {
                            id: signupColumn
                            anchors.fill: parent
                            anchors.margins: root.compactLayout ? 20 : 28
                            spacing: 0

                            Label {
                                text: backend.tr("signup")
                                color: theme.text
                                font.pixelSize: root.compactLayout ? 24 : 28
                                font.bold: true
                            }

                            Label {
                                Layout.topMargin: 10
                                text: trx("أنشئ مستخدمًا جديدًا وابنِ baseline سلوكي خاصًا بك.", "Create a new account and build your behavioral baseline.")
                                color: theme.muted
                                wrapMode: Text.Wrap
                                Layout.fillWidth: true
                            }

                            AppTextField {
                                id: signupDisplay
                                Layout.topMargin: 18
                                Layout.fillWidth: true
                                placeholderText: backend.tr("display_name")
                            }

                            AppTextField {
                                id: signupUsername
                                Layout.topMargin: 14
                                Layout.fillWidth: true
                                placeholderText: backend.tr("username")
                            }

                            AppTextField {
                                id: signupEmail
                                Layout.topMargin: 14
                                Layout.fillWidth: true
                                placeholderText: backend.tr("email")
                            }

                            AppTextField {
                                id: signupPassword
                                Layout.topMargin: 14
                                Layout.fillWidth: true
                                placeholderText: backend.tr("password")
                                echoMode: TextInput.Password
                            }

                            AppButton {
                                text: backend.tr("create_account")
                                role: "primary"
                                Layout.topMargin: 22
                                Layout.fillWidth: true
                                onClicked: backend.createAccount(signupDisplay.text, signupUsername.text, signupPassword.text, signupEmail.text)
                            }
                        }
                    }
                }
            }
        }
    }
}
