import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root
    property var theme: (parent && parent.theme !== undefined) ? parent.theme : backend.theme
    property var steps: []
    property var controller
    property int currentStep: 0
    property bool running: false
    property bool isArabic: backend.language === "ar"

    signal pageRequested(int pageIndex)
    signal completed(bool skipped)

    property var targetItem: null
    property rect targetRect: Qt.rect(0, 0, 0, 0)
    property bool targetSearchComplete: false
    property int pendingScrollAttempts: 0

    readonly property int stepTotal: stepCount()
    readonly property real safeMargin: width < 520 ? 10 : 16
    readonly property real highlightMargin: width < 520 ? 6 : 8
    readonly property real bubbleGap: height < 520 ? 10 : 14
    readonly property bool targetIntersectsView: targetItem !== null
                                             && targetRect.width > 1
                                             && targetRect.height > 1
                                             && targetRect.x < width
                                             && targetRect.y < height
                                             && targetRect.x + targetRect.width > 0
                                             && targetRect.y + targetRect.height > 0
    readonly property bool hasTarget: running && targetIntersectsView
    readonly property bool fallbackMode: running && targetSearchComplete && !hasTarget
    readonly property real highlightX: hasTarget ? clamp(targetRect.x - highlightMargin, 0, width) : Math.round(width / 2)
    readonly property real highlightY: hasTarget ? clamp(targetRect.y - highlightMargin, 0, height) : Math.round(height / 2)
    readonly property real highlightRight: hasTarget ? clamp(targetRect.x + targetRect.width + highlightMargin, 0, width) : highlightX
    readonly property real highlightBottom: hasTarget ? clamp(targetRect.y + targetRect.height + highlightMargin, 0, height) : highlightY
    readonly property real highlightW: hasTarget ? Math.max(0, highlightRight - highlightX) : 0
    readonly property real highlightH: hasTarget ? Math.max(0, highlightBottom - highlightY) : 0
    readonly property color dimColor: (theme && theme.overlayTint) ? theme.overlayTint : Qt.rgba(0, 0, 0, 0.58)
    readonly property color focusColor: (theme && (theme.primary || theme.info)) ? (theme.primary || theme.info) : "#22d3ee"

    visible: running
    enabled: running
    z: 900
    focus: running
    LayoutMirroring.enabled: root.isArabic
    LayoutMirroring.childrenInherit: true

    Keys.onReleased: function(event) {
        if (event.key === Qt.Key_Escape && root.running) {
            root.stop(true)
            event.accepted = true
        }
    }

    Shortcut {
        enabled: root.running
        sequence: "Esc"
        onActivated: root.stop(true)
    }

    onRunningChanged: {
        if (running) {
            targetSearchComplete = false
            pendingScrollAttempts = 0
            forceActiveFocus()
            syncStep()
        } else {
            targetItem = null
            targetRect = Qt.rect(0, 0, 0, 0)
            targetSearchComplete = false
            pendingScrollAttempts = 0
        }
    }

    onCurrentStepChanged: {
        if (running)
            syncStep()
    }

    onControllerChanged: {
        if (running) {
            targetSearchComplete = false
            refreshTimer.restart()
        }
    }

    onWidthChanged: updateTargetRect()
    onHeightChanged: updateTargetRect()

    function start() {
        if (stepCount() <= 0)
            return
        currentStep = clampStep(currentStep)
        targetSearchComplete = false
        if (!running)
            running = true
        else
            syncStep()
        forceActiveFocus()
    }

    function stop(skipped) {
        if (!running)
            return
        running = false
        targetItem = null
        targetRect = Qt.rect(0, 0, 0, 0)
        targetSearchComplete = false
        completed(skipped === true)
    }

    function next() {
        if (!running)
            return
        if (currentStep >= stepCount() - 1) {
            stop(false)
            return
        }
        currentStep = currentStep + 1
    }

    function previous() {
        if (!running || currentStep <= 0)
            return
        currentStep = currentStep - 1
    }

    function refreshTarget() {
        targetItem = null
        targetRect = Qt.rect(0, 0, 0, 0)
        targetSearchComplete = false

        if (!running || controller === null || controller === undefined) {
            targetSearchComplete = true
            return
        }

        var data = currentStepData()
        var targetName = stepTargetName(data)
        if (!targetName || typeof controller.tourTarget !== "function") {
            targetSearchComplete = true
            return
        }

        var item = controller.tourTarget(targetName)
        if (!isUsableTarget(item)) {
            targetSearchComplete = true
            return
        }

        targetItem = item
        updateTargetRect()
        targetSearchComplete = true
    }

    function currentStepData() {
        return stepAt(currentStep)
    }

    function currentTargetName() {
        return stepTargetName(currentStepData())
    }

    function stepCount() {
        if (!steps)
            return 0
        if (steps.length !== undefined)
            return steps.length
        if (steps.count !== undefined)
            return steps.count
        return 0
    }

    function stepAt(index) {
        if (!steps || index < 0 || index >= stepCount())
            return ({})
        if (typeof steps.get === "function")
            return steps.get(index)
        return steps[index] || ({})
    }

    function stepTargetName(data) {
        if (!data)
            return ""
        return data.target || data.targetName || data.name || ""
    }

    function stepPageIndex(data) {
        if (!data)
            return -1
        var value = data.pageIndex
        if (value === undefined)
            value = data.page
        if (value === undefined)
            return -1
        var numericValue = Number(value)
        return isNaN(numericValue) ? -1 : numericValue
    }

    function stepTitle(data) {
        if (!data)
            return ""
        return data.titleText || data.title || ""
    }

    function stepBody(data) {
        if (!data)
            return ""
        return data.bodyText || data.body || data.description || ""
    }

    function stepLabel(data) {
        if (data && data.stepText)
            return data.stepText
        var total = stepCount()
        if (total <= 0)
            return ""
        return isArabic ? ("الخطوة " + (currentStep + 1) + " من " + total)
                        : ("Step " + (currentStep + 1) + " of " + total)
    }

    function fallbackTitle(data) {
        var title = data ? (data.fallbackTitleText || data.fallbackTitle || "") : ""
        if (title.length > 0)
            return title
        var original = stepTitle(data)
        if (original.length > 0)
            return original
        return isArabic ? "شرح عام للصفحة" : "Page overview"
    }

    function fallbackBody(data) {
        if (data && (data.fallbackBodyText || data.fallbackBody))
            return data.fallbackBodyText || data.fallbackBody

        var pageIndex = stepPageIndex(data)
        if (pageIndex === 1)
            return isArabic ? "الحالة تظهر حسب ما يؤكده النظام. قد لا يظهر هذا الجزء الآن بسبب حجم الشاشة أو الحالة الحالية."
                            : "Status appears according to what the system confirms. This section may be hidden right now because of screen size or current state."
        if (pageIndex === 0)
            return isArabic ? "ابدأ جلسات التعلم عندما تكون جاهزًا. إذا لم يظهر هذا العنصر الآن، يمكنك متابعة الجولة من المركز."
                            : "Start learning sessions when you are ready. If this item is not visible right now, you can continue the guide from the center."
        return isArabic ? "هذا الجزء غير ظاهر الآن. يمكنك متابعة الجولة، وستعرض الواجهة العناصر المتاحة حسب الحالة وحجم الشاشة."
                        : "This target is not visible right now. You can continue the guide; the interface shows available items based on state and screen size."
    }

    function bubbleTitleText() {
        var data = currentStepData()
        return fallbackMode ? fallbackTitle(data) : stepTitle(data)
    }

    function bubbleBodyText() {
        var data = currentStepData()
        return fallbackMode ? fallbackBody(data) : stepBody(data)
    }

    function syncStep() {
        currentStep = clampStep(currentStep)
        targetSearchComplete = false
        pendingScrollAttempts = 0

        var data = currentStepData()
        var pageIndex = stepPageIndex(data)
        if (pageIndex >= 0)
            pageRequested(pageIndex)

        stepPrepareTimer.restart()
    }

    function prepareCurrentStepTarget() {
        if (!running)
            return

        pendingScrollAttempts += 1

        var targetName = currentTargetName()
        var didScroll = false
        if (targetName.length > 0 && controller !== null && controller !== undefined
                && typeof controller.scrollToTourTarget === "function") {
            didScroll = controller.scrollToTourTarget(targetName)
        }

        refreshTimer.restart()
        postScrollRefreshTimer.restart()

        if (!didScroll && pendingScrollAttempts < 8)
            stepPrepareTimer.restart()
    }

    function isUsableTarget(item) {
        if (!item)
            return false
        try {
            if (item.visible === false)
                return false
            if (item.width <= 1 || item.height <= 1)
                return false
        } catch (e) {
            return false
        }
        return true
    }

    function updateTargetRect() {
        if (!running || targetItem === null || targetItem === undefined)
            return
        try {
            if (!isUsableTarget(targetItem)) {
                targetItem = null
                targetRect = Qt.rect(0, 0, 0, 0)
                return
            }
            var point = targetItem.mapToItem(root, 0, 0)
            targetRect = Qt.rect(point.x, point.y, targetItem.width, targetItem.height)
        } catch (e) {
            targetItem = null
            targetRect = Qt.rect(0, 0, 0, 0)
        }
    }

    function clamp(value, minimum, maximum) {
        if (maximum < minimum)
            return minimum
        return Math.max(minimum, Math.min(maximum, value))
    }

    function clampStep(value) {
        var total = stepCount()
        if (total <= 0)
            return 0
        return Math.max(0, Math.min(total - 1, value))
    }

    function bubbleWidth() {
        return Math.max(240, Math.min(460, Math.max(0, width - safeMargin * 2)))
    }

    function bubbleHeight() {
        return Math.max(bubble.implicitHeight, bubble.height || 0)
    }

    function bubblePlacement() {
        if (!hasTarget)
            return "center"

        var bubbleW = bubbleWidth()
        var bubbleH = bubbleHeight()
        var belowSpace = height - (highlightY + highlightH) - safeMargin
        var aboveSpace = highlightY - safeMargin
        var rightSpace = width - (highlightX + highlightW) - safeMargin
        var leftSpace = highlightX - safeMargin

        if (belowSpace >= bubbleH + bubbleGap)
            return "below"
        if (aboveSpace >= bubbleH + bubbleGap)
            return "above"

        if (root.isArabic) {
            if (leftSpace >= bubbleW + bubbleGap)
                return "left"
            if (rightSpace >= bubbleW + bubbleGap)
                return "right"
        } else {
            if (rightSpace >= bubbleW + bubbleGap)
                return "right"
            if (leftSpace >= bubbleW + bubbleGap)
                return "left"
        }

        var bestPlacement = "below"
        var bestSpace = belowSpace
        if (aboveSpace > bestSpace) {
            bestPlacement = "above"
            bestSpace = aboveSpace
        }
        if (rightSpace > bestSpace) {
            bestPlacement = "right"
            bestSpace = rightSpace
        }
        if (leftSpace > bestSpace) {
            bestPlacement = "left"
            bestSpace = leftSpace
        }
        return bestPlacement
    }

    function bubbleX() {
        var bubbleW = bubble.width > 0 ? bubble.width : bubbleWidth()
        var minimum = safeMargin
        var maximum = width - bubbleW - safeMargin
        var placement = bubblePlacement()

        if (placement === "left")
            return clamp(highlightX - bubbleW - bubbleGap, minimum, maximum)
        if (placement === "right")
            return clamp(highlightX + highlightW + bubbleGap, minimum, maximum)
        if (!hasTarget)
            return clamp((width - bubbleW) / 2, minimum, maximum)

        var center = highlightX + highlightW / 2
        return clamp(center - bubbleW / 2, minimum, maximum)
    }

    function bubbleY() {
        var bubbleH = bubble.height > 0 ? bubble.height : bubbleHeight()
        var minimum = safeMargin
        var maximum = height - bubbleH - safeMargin
        var placement = bubblePlacement()

        if (!hasTarget)
            return clamp((height - bubbleH) / 2, minimum, maximum)
        if (placement === "below")
            return clamp(highlightY + highlightH + bubbleGap, minimum, maximum)
        if (placement === "above")
            return clamp(highlightY - bubbleH - bubbleGap, minimum, maximum)

        var center = highlightY + highlightH / 2
        return clamp(center - bubbleH / 2, minimum, maximum)
    }

    Timer {
        id: stepPrepareTimer
        interval: 80
        repeat: false
        onTriggered: root.prepareCurrentStepTarget()
    }

    Timer {
        id: refreshTimer
        interval: 45
        repeat: false
        onTriggered: root.refreshTarget()
    }

    Timer {
        id: postScrollRefreshTimer
        interval: 260
        repeat: false
        onTriggered: root.refreshTarget()
    }

    Timer {
        id: followTargetTimer
        interval: 90
        repeat: true
        running: root.running
        onTriggered: root.updateTargetRect()
    }

    MouseArea {
        id: blocker
        z: 0
        anchors.fill: parent
        acceptedButtons: Qt.AllButtons
        hoverEnabled: true
        preventStealing: true
        onPressed: function(mouse) {
            mouse.accepted = true
            root.forceActiveFocus()
        }
        onReleased: function(mouse) {
            mouse.accepted = true
        }
        onClicked: function(mouse) {
            mouse.accepted = true
        }
        onWheel: function(wheel) {
            wheel.accepted = true
        }
    }

    Rectangle {
        id: topDim
        z: 1
        x: 0
        y: 0
        width: root.width
        height: root.hasTarget ? root.highlightY : root.height
        color: root.dimColor
    }

    Rectangle {
        id: bottomDim
        z: 1
        x: 0
        y: root.hasTarget ? root.highlightY + root.highlightH : 0
        width: root.width
        height: root.hasTarget ? Math.max(0, root.height - y) : 0
        color: root.dimColor
    }

    Rectangle {
        id: leftDim
        z: 1
        x: 0
        y: root.highlightY
        width: root.hasTarget ? root.highlightX : 0
        height: root.hasTarget ? root.highlightH : 0
        color: root.dimColor
    }

    Rectangle {
        id: rightDim
        z: 1
        x: root.hasTarget ? root.highlightX + root.highlightW : 0
        y: root.highlightY
        width: root.hasTarget ? Math.max(0, root.width - x) : 0
        height: root.hasTarget ? root.highlightH : 0
        color: root.dimColor
    }

    Rectangle {
        id: targetFrame
        z: 2
        visible: root.hasTarget
        x: root.highlightX
        y: root.highlightY
        width: root.highlightW
        height: root.highlightH
        radius: Math.min(24, Math.max(12, Math.min(width, height) / 5))
        color: "transparent"
        border.color: root.focusColor
        border.width: 2
        opacity: 0.98
    }

    TourBubble {
        id: bubble
        z: 3
        theme: root.theme
        width: root.bubbleWidth()
        height: implicitHeight
        x: root.bubbleX()
        y: root.bubbleY()
        titleText: root.bubbleTitleText()
        bodyText: root.bubbleBodyText()
        stepText: root.stepLabel(root.currentStepData())
        canGoBack: root.currentStep > 0
        isLastStep: root.currentStep >= root.stepCount() - 1
        isArabic: root.isArabic
        onBackRequested: root.previous()
        onNextRequested: root.next()
        onSkipRequested: root.stop(true)
        onFinishRequested: root.stop(false)

        Behavior on x {
            NumberAnimation { duration: 140; easing.type: Easing.OutCubic }
        }

        Behavior on y {
            NumberAnimation { duration: 140; easing.type: Easing.OutCubic }
        }
    }
}
