.pragma library

var MAX_FIELD = 64

function clamp(raw, max) {
  var s = String(raw === undefined || raw === null ? "" : raw)
  var cap = max || MAX_FIELD
  return s.length > cap ? s.substring(0, cap) : s
}

function plain(value, max) {
  return String(value === undefined || value === null ? "" : value)
    .replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, "")
    .replace(/[<>&]/g, "")
    .substring(0, max || MAX_FIELD)
}

function parseSample(raw) {
  var text = String(raw || "")
  var meta = {
    present: false,
    onBattery: false,
    status: "",
    percent: "",
    packW: "",
    raplW: "",
    source: "none",
    significant: false
  }
  var rows = []
  var lines = text.split("\n")
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i]
    var eq = line.indexOf("=")
    if (eq <= 0) continue
    var key = line.substring(0, eq)
    var val = line.substring(eq + 1)
    if (key === "present") meta.present = val === "1"
    else if (key === "onbattery") meta.onBattery = val === "1"
    else if (key === "status") meta.status = val
    else if (key === "percent") meta.percent = val
    else if (key === "pack_w") meta.packW = val
    else if (key === "rapl_w") meta.raplW = val
    else if (key === "source") meta.source = val || "none"
    else if (key === "significant") meta.significant = val === "1"
    else if (key === "row") {
      var f = val.split("\t")
      if (!f[0]) continue
      rows.push({
        name: f[0],
        cpu: Number(f[1] || 0),
        watts: f[2] || "",
        n: Number(f[3] || 1)
      })
    }
  }
  return { meta: meta, rows: rows }
}

function formatWatts(value) {
  var n = Number(value)
  if (!isFinite(n) || n <= 0) return ""
  if (n < 0.1) return "<0.1 W"
  if (n < 10) return n.toFixed(1) + " W"
  return Math.round(n) + " W"
}

function formatCpu(value) {
  var n = Number(value)
  if (!isFinite(n) || n <= 0) return ""
  if (n < 1) return "<1%"
  return n.toFixed(n < 10 ? 1 : 0) + "%"
}

function sourceCaption(source, onBattery) {
  if (source === "rapl")
    return "Watt column is a share of CPU-package energy (RAPL). Display and discrete GPU are not in it."
  if (source === "battery")
    return "Watt column is a share of pack draw by CPU time. Display, GPU and idle sit in the remainder."
  if (onBattery)
    return "Pack draw is unavailable, so only CPU share is shown."
  return "On AC without readable RAPL there is no system watt number — charging current is not draw. CPU share only."
}

function heroMeta(meta) {
  if (meta.onBattery && meta.packW)
    return formatWatts(meta.packW) + " from the pack"
  if (meta.source === "rapl" && meta.raplW)
    return "~" + formatWatts(meta.raplW) + " CPU package"
  if (meta.status)
    return String(meta.status)
  return "No battery"
}

function elide(text, max) {
  var s = String(text || "")
  if (max <= 1 || s.length <= max) return s
  return s.substring(0, max - 1) + "…"
}
