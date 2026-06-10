import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia

Rectangle {
    id: preview
    objectName: "faceCameraPreview"
    property var backend
    property var theme: backend ? backend.theme : ({})
    property bool previewEnabled: false
    property bool consentGranted: false
    property bool backendActionInFlight: false
    property bool previewPausedForBackendCapture: false
    property string previewError: ""
    readonly property bool hasVideoInput: mediaDevices.videoInputs.length > 0
    readonly property bool shouldRunPreview: preview.previewEnabled && preview.consentGranted && !preview.backendActionInFlight && !preview.previewPausedForBackendCapture && preview.hasVideoInput && preview.previewError.length === 0
    readonly property string previewStatusText: !preview.consentGranted
                                                ? preview.safeText("face_camera_preview_locked")
                                                : (!preview.hasVideoInput
                                                   ? preview.safeText("face_preview_camera_unavailable")
                                                   : (preview.previewPausedForBackendCapture || preview.backendActionInFlight
                                                      ? preview.safeText("face_preview_paused_for_backend")
                                                      : (preview.previewError.length > 0
                                                         ? preview.safeText("face_preview_unavailable")
                                                         : preview.safeText("face_preview_live_title"))))
    readonly property string previewStatusDetail: !preview.consentGranted
                                                  ? preview.safeText("face_preview_consent_required_detail")
                                                  : (!preview.hasVideoInput
                                                     ? preview.safeText("face_camera_unavailable_body")
                                                     : (preview.previewPausedForBackendCapture || preview.backendActionInFlight
                                                        ? preview.safeText("face_preview_paused_detail")
                                                        : preview.safeText("face_preview_display_only_detail")))
    radius: 24
    color: preview.colorFor("surface1", "#101827")
    border.color: preview.shouldRunPreview ? preview.colorFor("accent", "#22d3ee") : preview.colorFor("border", "#303747")
    border.width: 1
    clip: true

    function safeText(key) {
        var translated = ""
        if (preview.backend && preview.backend.tr)
            translated = preview.backend.tr(key)
        return translated && translated !== key ? translated : preview.fallbackText(key)
    }

    function fallbackText(key) {
        if (key === "face_camera_preview_locked")
            return "Camera stays off until consent"
        if (key === "face_preview_camera_unavailable")
            return "No camera available for preview"
        if (key === "face_preview_paused_for_backend")
            return "Preview paused for backend capture"
        if (key === "face_preview_unavailable")
            return "Preview unavailable or permission denied"
        if (key === "face_preview_live_title")
            return "Live preview"
        if (key === "face_preview_consent_required_detail")
            return "Grant face-template consent before showing a local camera preview. No frame is saved."
        if (key === "face_camera_unavailable_body")
            return "Camera capture is unavailable in this environment. No image data is stored."
        if (key === "face_preview_paused_detail")
            return "BioAuth paused the display-only preview so the backend can use the camera safely. It resumes after the action finishes."
        if (key === "face_preview_display_only_detail")
            return "This preview only displays the camera feed. Capture starts only when you start enrollment or test confirmation."
        if (key === "face_preview_display_only_notice")
            return "Display-only preview · no local verification or saved frames"
        return key
    }

    function colorFor(name, fallback) {
        if (preview.theme && preview.theme[name] !== undefined)
            return preview.theme[name]
        return fallback
    }

    function pauseForBackendCapture() {
        preview.previewPausedForBackendCapture = true
    }

    function resumeAfterBackendCapture() {
        preview.previewError = ""
        preview.previewPausedForBackendCapture = false
    }

    function stopPreview() {
        preview.previewPausedForBackendCapture = true
    }

    function startPreview() {
        preview.resumeAfterBackendCapture()
    }

    MediaDevices {
        id: mediaDevices
    }

    CaptureSession {
        id: captureSession
        camera: camera
        videoOutput: videoOutput
    }

    Camera {
        id: camera
        cameraDevice: mediaDevices.defaultVideoInput
        active: preview.shouldRunPreview
        onErrorOccurred: function(error, errorString) {
            preview.previewError = preview.safeText("face_preview_unavailable")
        }
    }

    VideoOutput {
        id: videoOutput
        objectName: "facePreviewVideoOutput"
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectCrop
        mirrored: true
        visible: preview.shouldRunPreview
    }

    Rectangle {
        anchors.fill: parent
        color: preview.colorFor("surface1", "#101827")
        opacity: preview.shouldRunPreview ? 0.0 : 0.98
        visible: !preview.shouldRunPreview
    }

    Rectangle {
        anchors.fill: parent
        color: "transparent"
        visible: !preview.shouldRunPreview
        gradient: Gradient {
            GradientStop { position: 0.0; color: preview.colorFor("surface2", "#102033") }
            GradientStop { position: 1.0; color: preview.colorFor("surface0", "#07111f") }
        }
        opacity: 0.48
    }

    ColumnLayout {
        anchors.centerIn: parent
        width: Math.max(160, parent.width - 48)
        spacing: 10
        visible: !preview.shouldRunPreview

        Rectangle {
            Layout.alignment: Qt.AlignHCenter
            implicitWidth: 68
            implicitHeight: 68
            radius: 24
            color: preview.colorFor("surface2", "#102033")
            border.color: preview.shouldRunPreview ? preview.colorFor("success", "#22c55e") : preview.colorFor("border", "#303747")
            border.width: 1

            Label {
                anchors.centerIn: parent
                text: preview.consentGranted ? "◌" : "◇"
                color: preview.consentGranted ? preview.colorFor("accent", "#22d3ee") : preview.colorFor("muted", "#aab4c3")
                font.pixelSize: 31
                font.bold: true
            }
        }

        Label {
            objectName: "facePreviewStatusTitle"
            Layout.fillWidth: true
            text: preview.previewStatusText
            color: preview.colorFor("text", "#f4f7fb")
            font.pixelSize: 18
            font.bold: true
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
        }

        Label {
            objectName: "facePreviewStatusDetail"
            Layout.fillWidth: true
            text: preview.previewStatusDetail
            color: preview.colorFor("muted", "#aab4c3")
            font.pixelSize: 13
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            maximumLineCount: 5
            elide: Text.ElideRight
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "transparent"
        visible: preview.shouldRunPreview
        border.color: preview.colorFor("accent", "#22d3ee")
        border.width: 1
        opacity: 0.24
        radius: preview.radius - 3
        anchors.margins: 12
    }

    Item {
        anchors.fill: parent
        anchors.margins: 22
        visible: preview.shouldRunPreview

        Repeater {
            model: [
                { "x": 0, "y": 0, "h": false },
                { "x": 0, "y": 0, "h": true },
                { "x": 1, "y": 0, "h": false },
                { "x": 1, "y": 0, "h": true },
                { "x": 0, "y": 1, "h": false },
                { "x": 0, "y": 1, "h": true },
                { "x": 1, "y": 1, "h": false },
                { "x": 1, "y": 1, "h": true }
            ]

            delegate: Rectangle {
                width: modelData.h ? 44 : 3
                height: modelData.h ? 3 : 44
                radius: 2
                color: preview.colorFor("accent", "#22d3ee")
                opacity: 0.58
                x: modelData.x === 0 ? 0 : parent.width - width
                y: modelData.y === 0 ? 0 : parent.height - height
            }
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 54
        color: preview.colorFor("surface0", "#07111f")
        opacity: preview.shouldRunPreview ? 0.54 : 0.0
        visible: preview.shouldRunPreview
    }

    Label {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 14
        text: preview.previewStatusText
        color: preview.colorFor("text", "#f4f7fb")
        font.pixelSize: 13
        font.bold: true
        wrapMode: Text.Wrap
        maximumLineCount: 1
        elide: Text.ElideRight
        visible: preview.shouldRunPreview
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 58
        color: preview.colorFor("surface0", "#07111f")
        opacity: preview.shouldRunPreview ? 0.62 : 0.0
        visible: preview.shouldRunPreview
    }

    Label {
        objectName: "facePreviewDisplayOnlyNotice"
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 14
        text: preview.safeText("face_preview_display_only_notice")
        color: preview.colorFor("text", "#f4f7fb")
        font.pixelSize: 12
        wrapMode: Text.Wrap
        maximumLineCount: 2
        elide: Text.ElideRight
        visible: preview.shouldRunPreview
    }
}
