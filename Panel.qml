import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Bar icon plus popup: which processes are drawing power, ranked by CPU time.
//
//   left = panel · middle = refresh
//
// No root. App watts are a share of pack draw or RAPL. GPU PPT and fan
// RPM come from hwmon on the same sample.
Panel {
  id: root
  moduleName: "io.github.nepomuk-software.energyimpact"
  ipcTarget: "io.github.nepomuk-software.energyimpact"
  manageIpc: false

  readonly property alias service: energy

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property bool vertical: bar ? bar.vertical : false

  property int rowIndex: 0
  property bool cursorActive: false

  readonly property string barTooltip: {
    var lines = []
    if (energy.onBattery && energy.meta.packW)
      lines.push("Pack " + Model.formatWatts(energy.meta.packW))
    else if (energy.meta.status)
      lines.push(energy.meta.status)
    var cpu = Model.cpuLine(energy.meta)
    if (cpu) lines.push("CPU  " + cpu)
    var gpu = Model.gpuLine(energy.meta)
    if (gpu) lines.push("GPU  " + gpu)
    var fan = Model.formatRpm(energy.meta.fanRpm)
    if (fan) lines.push("Fan  " + fan)
    if (energy.rows.length > 0) {
      var top = energy.rows[0]
      var extra = top.watts ? "  ~" + Model.formatWatts(top.watts) : "  " + Model.formatCpu(top.cpu)
      lines.push(Model.plain(top.name) + extra)
    } else if (energy.sampled) {
      lines.push("Nothing using significant energy")
    } else {
      lines.push("Sampling…")
    }
    return lines.join("\n")
  }

  function handlePress(mouseButton) {
    if (mouseButton === Qt.MiddleButton) energy.refresh()
    else root.toggle()
  }

  function moveCursor(dy) {
    cursorActive = true
    if (energy.rows.length === 0) return
    rowIndex = Math.max(0, Math.min(energy.rows.length - 1, rowIndex + dy))
  }

  onOpenedChanged: if (!opened) cursorActive = false

  Service {
    id: energy
    settings: root.settings
    detailed: root.opened
  }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): string { energy.refresh(); return "ok" }
    function status(): string {
      var m = energy.meta
      var head = (m.onBattery ? "battery" : (m.status || "ac"))
      if (m.packW) head += " " + m.packW + "W"
      if (energy.rows.length === 0) {
        var idle = head + " idle"
        if (m.gpuBusy) idle += " gpu=" + m.gpuBusy + "%"
        if (m.fanRpm) idle += " fan=" + Math.round(Number(m.fanRpm))
        return idle
      }
      var top = energy.rows[0]
      var extra = head + " top=" + top.name + " cpu=" + top.cpu.toFixed(1)
           + (top.watts ? " ~" + top.watts + "W" : "")
      if (m.gpuBusy) extra += " gpu=" + m.gpuBusy + "%"
      if (m.fanRpm) extra += " fan=" + Math.round(Number(m.fanRpm))
      return extra
    }
  }

  visible: energy.showOnBar
  implicitWidth: energy.showOnBar ? face.implicitWidth : 0
  implicitHeight: energy.showOnBar ? face.implicitHeight : 0

  BarIconButton {
    id: face
    bar: root.bar
    text: "󰠠"
    dimmed: !energy.onBattery && !energy.significant
    active: energy.significant
    tooltipText: root.barTooltip
    onPressed: function (b) { root.handlePress(b) }
  }

  KeyboardPanel {
    id: panel
    anchorItem: face
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(520))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function (direction) { root.switchPanel(direction) }
      onMoveRequested: function (dx, dy) {
        if (dy === 0) return
        if (!root.cursorActive) { root.cursorActive = true; return }
        root.moveCursor(dy)
      }
      onTextKey: function (t) {
        if (String(t).toLowerCase() === "r") energy.refresh()
      }

      Flickable {
        id: panelFlick
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: column
          width: panelFlick.width
          spacing: Style.space(12)

          Item {
            width: parent.width
            implicitHeight: hero.implicitHeight
            PanelHero {
              id: hero
              width: parent.width
              title: "Energy"
              meta: Model.heroMeta(energy.meta)
              detail: energy.meta.percent ? (energy.meta.percent + "%") : ""
              foreground: root.foreground
              fontFamily: root.fontFamily
              iconComponent: Component {
                Text {
                  textFormat: Text.PlainText
                  text: "󰠠"
                  color: energy.significant ? root.urgent : root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.display
                }
              }
            }
          }

          Text {
            textFormat: Text.PlainText
            width: parent.width
            visible: energy.running && !energy.sampled
            text: "Sampling…"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          Column {
            width: parent.width
            spacing: Style.spacing.labelGap
            visible: Model.cpuLine(energy.meta) || energy.meta.fanRpm || energy.meta.gpuName

            PanelSectionHeader {
              text: "MACHINE"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            InfoPair {
              visible: Model.cpuLine(energy.meta) !== ""
              label: "CPU"
              value: Model.cpuLine(energy.meta)
            }
            InfoPair {
              visible: energy.meta.gpuName !== ""
              label: "GPU"
              value: Model.gpuLine(energy.meta)
            }
            InfoPair {
              visible: energy.meta.fanRpm !== ""
              label: energy.meta.fanN && Number(energy.meta.fanN) > 1 ? "Fans" : "Fan"
              value: Model.formatRpm(energy.meta.fanRpm)
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(6)

            PanelSectionHeader {
              text: "APPS USING ENERGY"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Text {
              textFormat: Text.PlainText
              visible: energy.sampled && energy.rows.length === 0
              width: parent.width
              text: "Nothing using significant energy."
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              wrapMode: Text.WordWrap
            }

            Repeater {
              model: energy.rows
              delegate: Rectangle {
                required property var modelData
                required property int index
                width: column.width
                implicitHeight: Style.spacing.popupRowHeight + Style.space(8)
                radius: Style.cornerRadius
                color: (root.cursorActive && root.rowIndex === index)
                       ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.07)
                       : "transparent"

                Text {
                  textFormat: Text.PlainText
                  anchors.left: parent.left
                  anchors.right: stats.left
                  anchors.rightMargin: Style.space(8)
                  anchors.verticalCenter: parent.verticalCenter
                  text: Model.plain(modelData.name)
                        + (modelData.n > 1 ? "  ·  " + modelData.n : "")
                  color: root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.bodySmall
                  elide: Text.ElideRight
                }

                Text {
                  id: stats
                  textFormat: Text.PlainText
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  text: {
                    var w = Model.formatWatts(modelData.watts)
                    var c = Model.formatCpu(modelData.cpu)
                    if (w) return "~" + w + "  ·  " + c
                    return c
                  }
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }
            }
          }

          Text {
            textFormat: Text.PlainText
            width: parent.width
            text: Model.sourceCaption(energy.meta.source, energy.onBattery)
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }
      }
    }
  }

  component InfoPair: Row {
    property string label: ""
    property string value: ""

    width: parent.width
    spacing: Style.space(8)

    Text {
      textFormat: Text.PlainText
      text: label
      color: root.foreground
      opacity: 0.6
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
    Item {
      width: Math.max(0, parent.width - parent.children[0].implicitWidth - parent.children[2].implicitWidth - parent.spacing * 2)
      height: 1
    }
    Text {
      textFormat: Text.PlainText
      text: value
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
    }
  }
}
