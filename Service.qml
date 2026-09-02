import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

// Samples CPU share and, when possible, watts. The Python helper does the
// /proc walk; this object only stores the last result.
Item {
  id: root

  property var settings: ({})
  property bool detailed: false

  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  readonly property bool hideOnAc: setting("hideOnAc", false) === true
  readonly property int intervalSec: Math.max(2, Number(setting("intervalSec", 4)))
  readonly property int idleIntervalSec: Math.max(intervalSec, Number(setting("idleIntervalSec", 15)))

  readonly property string sampleScript: Qt.resolvedUrl("energy_sample.py").toString().replace(/^file:\/\//, "")

  property var meta: ({
    present: false,
    onBattery: false,
    status: "",
    percent: "",
    packW: "",
    raplW: "",
    source: "none",
    significant: false,
    cpuTempC: "",
    fanRpm: "",
    fanN: "",
    gpuName: "",
    gpuW: "",
    gpuTempC: "",
    gpuBusy: "",
    gpuMhz: ""
  })
  property var rows: []
  property bool sampled: false
  property bool running: false

  readonly property bool onBattery: meta.onBattery === true
  readonly property bool significant: meta.significant === true
  readonly property bool hasWatts: meta.source === "rapl" || meta.source === "battery"
  readonly property bool showOnBar: {
    if (hideOnAc && meta.present && !onBattery && sampled) return false
    return true
  }

  function refresh() {
    if (sampleProc.running) return
    sampleProc.running = true
  }

  function apply(raw) {
    var parsed = Model.parseSample(raw)
    meta = parsed.meta
    rows = parsed.rows
    sampled = true
  }

  Process {
    id: sampleProc
    command: ["python3", root.sampleScript, "--interval", "0.6"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.apply(text)
    }
    onRunningChanged: root.running = running
  }

  Timer {
    interval: (root.detailed ? root.intervalSec : root.idleIntervalSec) * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  onDetailedChanged: if (detailed) root.refresh()
}
