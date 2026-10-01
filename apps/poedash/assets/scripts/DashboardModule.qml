import Quickshell
import Quickshell.Io
import QtQuick
import QtQuick.Layouts
import qs.CustomTheme

Item {
    id: dashboardControls
    property string dashboardRoot: "@@DASHBOARD_ROOT@@"
    property bool dashboardEnabled: true
    property bool collapsed: false
    property var navButtons: [toggleButton, updateButton]
    implicitWidth: controls.implicitWidth
    implicitHeight: 30

    FileView {
        id: disabledMarker
        path: dashboardControls.dashboardRoot + "/disabled"
        watchChanges: true
        printErrors: false
        onLoaded: dashboardControls.dashboardEnabled = false
        onLoadFailed: dashboardControls.dashboardEnabled = true
        onFileChanged: reload()
    }
    Timer { interval: 750; running: true; repeat: true; onTriggered: disabledMarker.reload() }
    RowLayout {
        id: controls
        anchors.centerIn: parent
        spacing: 4
        Rectangle {
            id: toggleButton
            property bool focused: false
            function activate(): void {
                Quickshell.execDetached(["python3", dashboardControls.dashboardRoot + "/scripts/dashboard-control.py",
                                         "--root", dashboardControls.dashboardRoot, "toggle"])
            }
            implicitWidth: 34; implicitHeight: 28; radius: 14
            color: dashboardControls.dashboardEnabled ? Theme.primary : Theme.background
            border.width: 1; border.color: Theme.primary
            Text { anchors.centerIn: parent; text: dashboardControls.dashboardEnabled ? "󰍹" : "󰶐"; color: dashboardControls.dashboardEnabled ? Theme.background : Theme.primary; font.pixelSize: 18; font.bold: true }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: toggleButton.activate() }
        }
        Rectangle {
            id: updateButton
            property bool focused: false
            function activate(): void {
                Quickshell.execDetached(["python3", dashboardControls.dashboardRoot + "/scripts/dashboard-control.py",
                                         "--root", dashboardControls.dashboardRoot, "update"])
            }
            implicitWidth: 32; implicitHeight: 28; radius: 14
            color: updateMouse.containsMouse ? Theme.primary : "transparent"
            border.width: 1; border.color: Theme.primary
            Text { anchors.centerIn: parent; text: "↻"; color: updateMouse.containsMouse ? Theme.background : Theme.primary; font.pixelSize: 18; font.bold: true }
            MouseArea { id: updateMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: updateButton.activate() }
        }
    }
}
