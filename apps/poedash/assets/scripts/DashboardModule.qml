import Quickshell
import Quickshell.Io
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as Controls
import qs.CustomTheme

Item {
    id: dashboardControls
    property string dashboardRoot: "@@DASHBOARD_ROOT@@"
    property string dashboardName: "@@DASHBOARD_NAME@@"
    property bool dashboardEnabled: true
    property bool collapsed: false
    property var updateStatus: ({})
    property double now: Date.now() / 1000
    property double pendingUntil: 0
    readonly property bool updating: updateStatus.state === "running" || now < pendingUntil
    readonly property bool showUpdateStatus: updating || (updateStatus.state !== undefined && now - (updateStatus.updated || 0) < 12)
    readonly property string updateStage: now < pendingUntil ? "Starting" : (updateStatus.stage || "Updating")
    readonly property real updateProgress: now < pendingUntil ? .05 : Math.max(0, Math.min(1, updateStatus.progress || 0))
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
    FileView {
        id: updateState
        path: (Quickshell.env("XDG_CACHE_HOME") || Quickshell.env("HOME") + "/.cache") + "/poedash/update-status.json"
        watchChanges: true
        printErrors: false
        onLoaded: {
            try {
                dashboardControls.updateStatus = JSON.parse(text())
                if (dashboardControls.updateStatus.state === "running") dashboardControls.pendingUntil = 0
            } catch (error) { dashboardControls.updateStatus = ({}) }
        }
        onLoadFailed: dashboardControls.updateStatus = ({})
        onFileChanged: reload()
    }
    Timer {
        interval: 500; running: true; repeat: true
        onTriggered: {
            dashboardControls.now = Date.now() / 1000
            disabledMarker.reload()
            updateState.reload()
        }
    }
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
            Controls.ToolTip.visible: updateMouse.containsMouse
            Controls.ToolTip.text: dashboardControls.updating ? dashboardControls.updateStage + " " + dashboardControls.dashboardName + "…"
                : dashboardControls.updateStatus.state === "failed" ? dashboardControls.updateStatus.detail : "Update " + dashboardControls.dashboardName
            Controls.ToolTip.delay: 350
            property bool focused: false
            function activate(): void {
                if (dashboardControls.updating) return
                dashboardControls.pendingUntil = Date.now() / 1000 + 3
                Quickshell.execDetached(["python3", dashboardControls.dashboardRoot + "/scripts/dashboard-control.py",
                                         "--root", dashboardControls.dashboardRoot, "update"])
            }
            implicitWidth: dashboardControls.showUpdateStatus ? 136 : 32; implicitHeight: 28; radius: 14
            color: updateMouse.containsMouse && !dashboardControls.updating ? Theme.primary : "transparent"
            border.width: 1; border.color: Theme.primary
            Row {
                anchors.centerIn: parent
                spacing: 6
                Text {
                    text: dashboardControls.showUpdateStatus && dashboardControls.updateStatus.state === "failed" ? "!" : "↻"
                    color: updateMouse.containsMouse && !dashboardControls.updating ? Theme.background : Theme.primary
                    font.pixelSize: 18; font.bold: true
                    NumberAnimation on rotation { from: 0; to: 360; duration: 1400; loops: Animation.Infinite; running: dashboardControls.updating }
                }
                Text {
                    visible: dashboardControls.showUpdateStatus
                    anchors.verticalCenter: parent.verticalCenter
                    text: dashboardControls.updateStage
                    color: updateMouse.containsMouse && !dashboardControls.updating ? Theme.background : Theme.primary
                    font.pixelSize: 11
                }
            }
            Rectangle {
                visible: dashboardControls.showUpdateStatus
                anchors.bottom: parent.bottom; anchors.bottomMargin: 3
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width - 22; height: 2; radius: 1
                color: Theme.primary; opacity: .25
            }
            Rectangle {
                visible: dashboardControls.showUpdateStatus
                anchors.bottom: parent.bottom; anchors.bottomMargin: 3
                x: 11; width: (parent.width - 22) * dashboardControls.updateProgress
                height: 2; radius: 1; color: Theme.primary
                Behavior on width { NumberAnimation { duration: 250 } }
            }
            MouseArea { id: updateMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: dashboardControls.updating ? Qt.BusyCursor : Qt.PointingHandCursor; onClicked: updateButton.activate() }
        }
    }
}
