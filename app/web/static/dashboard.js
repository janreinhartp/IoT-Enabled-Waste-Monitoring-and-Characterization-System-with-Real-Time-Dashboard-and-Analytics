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

  // ---- Feedback ----
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

  // ---- Two-step Analyze → Tare → Record ----
  const btnAnalyze     = document.getElementById("btn-analyze");
  const btnCommit      = document.getElementById("btn-commit");
  const btnClearPend   = document.getElementById("btn-clear-pending");
  const btnResetTare   = document.getElementById("btn-reset-tare");
  const pendingPreview = document.getElementById("pending-preview");
  const pendingLabelEl = document.getElementById("pending-label-text");
  const pendingConfEl  = document.getElementById("pending-conf-text");
  const pendingImgEl   = document.getElementById("pending-img");

  function setPendingUI(pending) {
    if (!btnCommit) return;
    if (pending && pending.pending) {
      btnCommit.disabled = false;
      if (btnClearPend) btnClearPend.style.display = "";
      if (pendingPreview) pendingPreview.style.display = "";
      if (pendingLabelEl) pendingLabelEl.textContent = pending.label || "unknown";
      if (pendingConfEl) pendingConfEl.textContent =
        pending.confidence != null ? "(" + Math.round(pending.confidence * 100) + "%)" : "";
      if (pendingImgEl) {
        pendingImgEl.src = "/images/pending?t=" + Date.now();
        pendingImgEl.style.display = "";
      }
    } else {
      btnCommit.disabled = true;
      if (btnClearPend) btnClearPend.style.display = "none";
      if (pendingPreview) pendingPreview.style.display = "none";
    }
  }

  // Restore pending state on page load
  fetch("/api/pending_detection")
    .then((r) => r.json())
    .then(setPendingUI)
    .catch(() => {});

  if (btnAnalyze) {
    btnAnalyze.addEventListener("click", () => {
      btnAnalyze.disabled = true;
      btnAnalyze.textContent = "Analyzing…";
      setFeedback("", true);
      fetch("/api/analyze", { method: "POST" })
        .then((r) => r.json())
        .then((data) => {
          if (data.error) { setFeedback("Error: " + data.error, false); return; }
          if (data.status === "no_detection") {
            setFeedback("Nothing detected — try again.", false);
            setPendingUI({ pending: false });
          } else {
            setFeedback("Item analyzed: " + data.label + ". Now place on scale and click Record Weight.", true);
            setPendingUI({ pending: true, ...data });
          }
        })
        .catch(() => setFeedback("Analyze request failed.", false))
        .finally(() => {
          btnAnalyze.disabled = false;
          btnAnalyze.textContent = "🔬 Analyze";
        });
    });
  }

  if (btnCommit) {
    btnCommit.addEventListener("click", () => {
      btnCommit.disabled = true;
      btnCommit.textContent = "Recording…";
      setFeedback("", true);
      fetch("/api/commit", { method: "POST" })
        .then((r) => r.json())
        .then((data) => {
          if (data.error) {
            setFeedback("Error: " + data.error, false);
            btnCommit.disabled = false;
          } else {
            setFeedback("Recorded at " + data.weight_g + " g ✓", true);
            setPendingUI({ pending: false });
          }
        })
        .catch(() => {
          setFeedback("Commit request failed.", false);
          btnCommit.disabled = false;
        })
        .finally(() => { btnCommit.textContent = "⚖ Record Weight"; });
    });
  }

  if (btnClearPend) {
    btnClearPend.addEventListener("click", () => {
      fetch("/api/commit", { method: "DELETE" }).catch(() => {});  // best-effort
      setPendingUI({ pending: false });
      setFeedback("Pending analysis cleared.", true);
    });
  }

  if (btnResetTare) {
    btnResetTare.addEventListener("click", () => {
      btnResetTare.disabled = true;
      btnResetTare.textContent = "Resetting…";
      fetch("/api/reset_tare", { method: "POST" })
        .then((r) => r.json())
        .then((data) => {
          if (data.error) {
            setFeedback("Tare reset failed: " + data.error, false);
          } else {
            setFeedback("Tare reset — scale zeroed.", true);
          }
        })
        .catch(() => setFeedback("Tare reset request failed.", false))
        .finally(() => {
          btnResetTare.disabled = false;
          btnResetTare.textContent = "↺ Reset Tare";
        });
    });
  }

  // ---- Live AI preview via Socket.IO (pushed every ai_preview_interval_s) ----
  const aiLiveDot = document.getElementById("ai-live-dot");
  const aiLastUpdated = document.getElementById("ai-last-updated");

  socket.on("ai_preview", (msg) => {
    showDetections(msg.detections, null);
    // Pulse the live indicator
    if (aiLiveDot) {
      aiLiveDot.classList.remove("ai-dot-pulse");
      void aiLiveDot.offsetWidth; // force reflow to restart animation
      aiLiveDot.classList.add("ai-dot-pulse");
    }
    if (aiLastUpdated) {
      const now = new Date();
      aiLastUpdated.textContent = now.toLocaleTimeString();
    }
  });
})();
