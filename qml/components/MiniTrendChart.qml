import QtQuick

Item {
    id: root
    property var dataPoints: []
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    property color strokeColor: theme.accent
    property color fillColor: theme.isDark ? "#1a22d3ee" : "#160891b2"
    property color gridColor: theme.border
    property real lineWidth: 2.2
    property bool showArea: true
    property bool showEndpoint: true
    implicitWidth: 220
    implicitHeight: 84

    function repaint() {
        canvas.requestPaint()
    }

    onDataPointsChanged: repaint()
    onStrokeColorChanged: repaint()
    onFillColorChanged: repaint()
    onGridColorChanged: repaint()
    onWidthChanged: repaint()
    onHeightChanged: repaint()

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true

        onPaint: {
            var ctx = getContext("2d")
            if (ctx.reset)
                ctx.reset()
            ctx.clearRect(0, 0, width, height)

            var pts = root.dataPoints || []
            if (pts.length < 2)
                return

            var minVal = pts[0]
            var maxVal = pts[0]
            for (var i = 1; i < pts.length; ++i) {
                minVal = Math.min(minVal, pts[i])
                maxVal = Math.max(maxVal, pts[i])
            }
            if (maxVal === minVal) {
                maxVal += 1
                minVal -= 1
            }

            function px(index) {
                return (width - 1) * index / (pts.length - 1)
            }

            function py(value) {
                var normalized = (value - minVal) / (maxVal - minVal)
                return height - 6 - normalized * (height - 18)
            }

            ctx.strokeStyle = root.gridColor
            ctx.globalAlpha = 0.18
            ctx.lineWidth = 1
            for (var line = 1; line <= 2; ++line) {
                var gy = height * line / 3
                ctx.beginPath()
                ctx.moveTo(0, gy)
                ctx.lineTo(width, gy)
                ctx.stroke()
            }
            ctx.globalAlpha = 1.0

            if (root.showArea) {
                ctx.beginPath()
                ctx.moveTo(px(0), py(pts[0]))
                for (var areaIndex = 1; areaIndex < pts.length; ++areaIndex)
                    ctx.lineTo(px(areaIndex), py(pts[areaIndex]))
                ctx.lineTo(width, height)
                ctx.lineTo(0, height)
                ctx.closePath()
                ctx.fillStyle = root.fillColor
                ctx.fill()
            }

            ctx.beginPath()
            ctx.moveTo(px(0), py(pts[0]))
            for (var pointIndex = 1; pointIndex < pts.length; ++pointIndex)
                ctx.lineTo(px(pointIndex), py(pts[pointIndex]))
            ctx.strokeStyle = root.strokeColor
            ctx.lineWidth = root.lineWidth
            ctx.lineCap = "round"
            ctx.lineJoin = "round"
            ctx.stroke()

            if (root.showEndpoint) {
                var lastX = px(pts.length - 1)
                var lastY = py(pts[pts.length - 1])
                ctx.beginPath()
                ctx.arc(lastX, lastY, 4, 0, Math.PI * 2, false)
                ctx.fillStyle = root.strokeColor
                ctx.fill()
            }
        }
    }

    Component.onCompleted: repaint()
}
