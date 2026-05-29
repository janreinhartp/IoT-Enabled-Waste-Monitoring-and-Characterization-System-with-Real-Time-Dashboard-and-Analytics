(function () {
  "use strict";
  const socket = io();

  const liveWeightEl = document.getElementById("live-weight");
  const liveStateEl = document.getElementById("live-state");
  const scaleBarEl = document.getElementById("scale-status-bar");
  const scaleDetailEl = document.getElementById("scale-status-detail");
  const latestCard = document.getElementById("latest-card");
  const tbody = document.querySelector("#events-table tbody");

  socket.on("connect", () => {
    if (liveStateEl) liveStateEl.textContent = "connected";
  });
  socket.on("disconnect", () => {
    if (liveStateEl) liveStateEl.textContent = "disconnected";
  });

  socket.on("weight", (msg) => {
    if (!liveWeightEl) return;
    const g = Number(msg.grams || 0);
    liveWeightEl.innerHTML = g.toFixed(1) + ' <span class="unit">g</span>';
  });

  const STATE_LABELS = {
    idle: "⏳ Waiting for item (min " ,
    stabilizing: "📊 Stabilizing…",
    cooldown: "✅ Recorded — remove item to reset",
  };
  const STATE_COLORS = {
    idle: "#6b7280",
    stabilizing: "#f59e0b",
    cooldown: "#10b981",
  };

  socket.on("scale_status", (s) => {
    if (!liveStateEl) return;
    const state = s.state || "idle";
    const color = STATE_COLORS[state] || "#6b7280";

    // State label
    let label;
    if (state === "idle") {
      label = "⏳ Waiting — need ≥ " + s.min_weight_g + " g";
    } else if (state === "stabilizing") {
      label = "📊 Stabilizing… (" + s.window_samples + " / " + s.stability_window + " samples)";
    } else {
      label = "✅ Recorded — remove item to reset";
    }
    liveStateEl.textContent = label;
    liveStateEl.style.color = color;

    // Progress bar (stability window fill)
    if (scaleBarEl) {
      const pct = state === "stabilizing"
        ? Math.min(100, Math.round((s.window_samples / s.stability_window) * 100))
        : state === "cooldown" ? 100 : 0;
      scaleBarEl.style.width = pct + "%";
      scaleBarEl.style.background = color;
    }

    // Detail line
    if (scaleDetailEl) {
      if (state === "stabilizing") {
        scaleDetailEl.textContent =
          "Weight: " + s.weight_g + " g  |  Need " +
          s.stability_window + " stable samples within ±" + s.stability_g + " g stddev";
      } else {
        scaleDetailEl.textContent = "";
      }
    }
  });

  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));
  }

  function renderLatest(e) {
    if (!latestCard) return;
    latestCard.innerHTML =
      '<img id="latest-img" src="/images/' + e.id + '?t=' + Date.now() + '" alt="latest">' +
      '<div class="latest-info">' +
      '<div class="latest-label">' + escapeHtml(e.detected_label) + '</div>' +
      '<div class="latest-cat">' + escapeHtml(e.waste_category) + '</div>' +
      '<div class="latest-weight">' + Number(e.weight_grams).toFixed(1) + ' g</div>' +
      '<div class="latest-conf">conf ' + Math.round((e.confidence || 0) * 100) + '%</div>' +
      '</div>';
  }

  function prependRow(e) {
    if (!tbody) return;
    const tr = document.createElement("tr");
    tr.dataset.id = e.id;
    tr.innerHTML =
      '<td>' + escapeHtml(e.id) + '</td>' +
      '<td>' + escapeHtml(e.timestamp) + '</td>' +
      '<td>' + escapeHtml(e.detected_label) + '</td>' +
      '<td>' + escapeHtml(e.waste_category) + '</td>' +
      '<td>' + Number(e.weight_grams).toFixed(1) + '</td>' +
      '<td>' + Math.round((e.confidence || 0) * 100) + '%</td>' +
      '<td><a href="/images/' + encodeURIComponent(e.id) + '" target="_blank">view</a></td>';
    tbody.insertBefore(tr, tbody.firstChild);
    while (tbody.children.length > 20) {
      tbody.removeChild(tbody.lastChild);
    }
  }

  socket.on("new_event", (e) => {
    renderLatest(e);
    prependRow(e);
  });

  // ---- Manual record button ----
  const btnRecord = document.getElementById("btn-record");
  const btnScan = document.getElementById("btn-scan");
  const recordFeedback = document.getElementById("record-feedback");
  const detectionPreview = document.getElementById("detection-preview");
  const detectionPreviewBody = document.getElementById("detection-preview-body");

  const CATEGORY_COLORS = {
    plastic: "#3b82f6",
    paper:   "#f59e0b",
    metal:   "#6b7280",
    glass:   "#10b981",
    organic: "#84cc16",
  };

  function setFeedback(msg, ok) {
    if (!recordFeedback) return;
    recordFeedback.textContent = msg;
    recordFeedback.style.color = ok ? "#10b981" : "#ef4444";
    clearTimeout(recordFeedback._timer);
    recordFeedback._timer = setTimeout(() => { recordFeedback.textContent = ""; }, 4000);
  }

  function showDetections(detections, weight_g) {
    if (!detectionPreview || !detectionPreviewBody) return;
    if (!detections || detections.length === 0) {
      detectionPreviewBody.innerHTML =
        '<span class="det-none">Nothing recognised — check AI backend, model path, and confidence threshold</span>';
    } else {
      detectionPreviewBody.innerHTML = detections.map((d) => {
        const mapped = !!d.category;
        const color = mapped ? (CATEGORY_COLORS[d.category] || "#9ca3af") : "#f97316";
        const pct = Math.round(d.confidence * 100);
        const catText = mapped ? d.category : "not mapped \u26a0";
        const belowThresh = d.confidence < 0.4;
        return '<div class="det-row' + (belowThresh ? " det-row-dim" : "") + '">' +
          '<span class="det-label">' + escapeHtml(d.label) + '</span>' +
          '<span class="det-arrow">\u2192</span>' +
          '<span class="det-cat" style="color:' + color + '">' + escapeHtml(catText) + '</span>' +
          '<span class="det-conf' + (belowThresh ? " det-conf-low" : "") + '">' + pct + '%' +
          (belowThresh ? ' <small>(below threshold)</small>' : '') + '</span>' +
          '</div>';
      }).join("");
    }
    detectionPreview.style.display = "block";
  }

  function runScan(andRecord) {
    if (btnScan) btnScan.disabled = true;
    if (btnRecord) btnRecord.disabled = true;
    fetch("/api/detect/preview", { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        if (data.error) {
          setFeedback("Error: " + data.error, false);
          return;
        }
        showDetections(data.detections, data.weight_g);
        if (andRecord) {
          if (!data.detections || data.detections.length === 0) {
            setFeedback("Nothing detected — not recorded.", false);
          } else {
            // detections found — now actually record
            fetch("/api/record", { method: "POST" })
              .then((r) => r.json())
              .then((rec) => {
                if (rec.error) {
                  setFeedback("Error: " + rec.error, false);
                } else {
                  setFeedback("Recording at " + rec.weight_g + " g…", true);
                }
              })
              .catch(() => setFeedback("Record request failed.", false));
          }
        }
      })
      .catch(() => setFeedback("Scan failed.", false))
      .finally(() => {
        if (btnScan) btnScan.disabled = false;
        if (btnRecord) btnRecord.disabled = false;
      });
  }

  if (btnRecord) {
    btnRecord.addEventListener("click", () => runScan(true));
  }
  if (btnScan) {
    btnScan.addEventListener("click", () => runScan(false));
  }
})();
