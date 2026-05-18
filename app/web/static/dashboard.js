(function () {
  "use strict";
  const socket = io();

  const liveWeightEl = document.getElementById("live-weight");
  const liveStateEl = document.getElementById("live-state");
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
