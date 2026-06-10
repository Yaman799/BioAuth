import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    objectName: "modelEvaluationPage"
    property var rootWindow
    property var theme: rootWindow ? rootWindow.theme : backend.theme
    property bool compactLayout: rootWindow ? rootWindow.compactLayout : width < 1180

    function trx(arText, enText) { return rootWindow ? rootWindow.trx(arText, enText) : enText }

    ScrollView {
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

        ColumnLayout {
            width: parent.width
            spacing: root.compactLayout ? 14 : 18

            GlassCard {
                objectName: "modelEvaluationPlaceholderCard"
                Layout.fillWidth: true
                implicitHeight: placeholderColumn.implicitHeight + 32

                ColumnLayout {
                    id: placeholderColumn
                    anchors.fill: parent
                    anchors.margins: root.compactLayout ? 16 : 22
                    spacing: 14

                    SectionHeader {
                        title: root.trx("Model Evaluation", "Model Evaluation")
                        subtitle: root.trx(
                            "صفحة عرض فقط في Phase 3. تقارير EER وFAR وFRR والعتبات ستُربط من backend في مرحلة لاحقة.",
                            "Display-only page for Phase 3. EER, FAR, FRR, and threshold reports will be wired from the backend in a later phase."
                        )
                        Layout.fillWidth: true
                    }

                    Label {
                        objectName: "modelEvaluationPlaceholderNotice"
                        text: root.trx(
                            "هذه الصفحة لا ترسم charts وهمية ولا تعرض مقاييس مختلقة. لا تغيّر production approval أو training أو runtime state.",
                            "This page does not render fake charts or invented metrics. It does not change production approval, training, or runtime state."
                        )
                        color: theme.text
                        wrapMode: Text.Wrap
                        Layout.fillWidth: true
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 10

                        InfoPill {
                            textValue: root.trx("Report UI: later phase", "Report UI: later phase")
                            pillTone: "details"
                        }
                        InfoPill {
                            textValue: root.trx("No fake metrics", "No fake metrics")
                            pillTone: "warn"
                        }
                        InfoPill {
                            textValue: root.trx("Display only", "Display only")
                            pillTone: "info"
                        }
                    }
                }
            }
        }
    }
}
