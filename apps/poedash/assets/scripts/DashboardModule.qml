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
    Process {
        id: toggleProcess
        command: ["python3", dashboardControls.dashboardRoot + "/scripts/dashboard-control.py",
                  "--root", dashboardControls.dashboardRoot, "toggle"]
        onExited: disabledMarker.reload()
    }
    Process {
        id: updateProcess
        command: ["python3", dashboardControls.dashboardRoot + "/scripts/dashboard-control.py",
                  "--root", dashboardControls.dashboardRoot, "update"]
    }
    RowLayout {
        id: controls
        anchors.centerIn: parent
        spacing: 4
        BarButton {
            id: toggleButton
            iconSrc: dashboardControls.dashboardEnabled
                ? "image://icon/view-visible-symbolic"
                : "image://icon/view-hidden-symbolic"
            onClicked: toggleProcess.running = true
        }
        BarButton {
            id: updateButton
            iconSrc: "image://icon/view-refresh-symbolic"
            onClicked: updateProcess.running = true
        }
    }
}
