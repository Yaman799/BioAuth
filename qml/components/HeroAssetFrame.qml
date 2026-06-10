import QtQuick
import "../theme/Ui.js" as Ui

Item {
    id: root

    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    property url sourceUrl: ""
    property string tone: "info"

    // Public API kept stable for existing HeroAssetFrame call sites.
    property real cornerRadius: 28
    property real framePadding: 0
    property int imageFillMode: Image.PreserveAspectCrop
    property real imageOpacity: 1.0
    property real overlayOpacity: 0.0
    property bool showFrame: false
    property real imageBleed: 0

    // Kept for compatibility with the earlier visual API. The integrated hero
    // assets carry their own transparent feather, so these default to zero to
    // avoid a visible surface-colored rectangle over the artwork.
    property real edgeFadeOpacity: 0.0
    property real ambientWashOpacity: 0.0

    readonly property color accentColor: Ui.roleColor(theme, tone)
    readonly property color softSurface: Ui.colorToken(theme, "surface")
    readonly property color frameBorder: Ui.colorToken(theme, "border")
    readonly property real effectiveImageOpacity: Math.max(0.0, Math.min(root.imageOpacity, 1.0))
    readonly property real effectiveOverlayOpacity: Math.max(0.0, Math.min(root.overlayOpacity, 0.12))
    readonly property real effectiveAmbientWashOpacity: Math.max(0.0, Math.min(root.ambientWashOpacity, 0.08))
    readonly property real safeImageMargin: Math.max(-32, root.framePadding - root.imageBleed)

    implicitWidth: 320
    implicitHeight: 260
    clip: true

    Image {
        id: heroImage
        anchors.fill: parent
        anchors.margins: root.safeImageMargin
        source: root.sourceUrl
        fillMode: root.imageFillMode
        smooth: true
        asynchronous: true
        mipmap: true
        cache: true
        opacity: root.effectiveImageOpacity
    }

    // Optional light brand tint for future call sites. It is off by default so
    // transparent hero assets inherit the exact card/window color underneath.
    Rectangle {
        anchors.fill: parent
        radius: root.cornerRadius
        color: root.accentColor
        opacity: root.effectiveAmbientWashOpacity
        border.color: "transparent"
    }

    // Optional surface wash for future call sites. Kept off on user hero images
    // because the previous full-surface wash was the source of the color mismatch.
    Rectangle {
        anchors.fill: parent
        radius: root.cornerRadius
        color: root.softSurface
        opacity: root.effectiveOverlayOpacity
        border.color: "transparent"
    }

    Rectangle {
        anchors.fill: parent
        radius: root.cornerRadius
        color: "transparent"
        border.color: root.frameBorder
        border.width: 1
        opacity: root.showFrame ? (theme.isDark ? 0.48 : 0.36) : 0
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: Math.max(0, root.cornerRadius - 1)
        color: "transparent"
        border.color: root.accentColor
        border.width: 1
        opacity: root.showFrame ? (theme.isDark ? 0.10 : 0.07) : 0
    }
}
