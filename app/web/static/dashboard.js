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
})();
