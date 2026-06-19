(function () {
  "use strict";
  const categories = window.WASTE_CATEGORIES || [];
  const colorBySlug = Object.fromEntries(
    categories.map((c) => [c.slug, c.color || "#888"])
  );
  const nameBySlug = Object.fromEntries(
    categories.map((c) => [c.slug, c.name || c.slug])
  );

  async function fetchJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  function formatGrams(g) {
    if (g >= 1000) return (g / 1000).toFixed(2) + " kg";
    return g.toFixed(1) + " g";
  }

  async function loadStats() {
    const [all, today] = await Promise.all([
      fetchJSON("/api/summary?window=all"),
      fetchJSON("/api/summary?window=today"),
    ]);
    document.getElementById("stat-total-count").textContent = all.total_count;
    document.getElementById("stat-total-weight").textContent = formatGrams(all.total_weight_g);
    document.getElementById("stat-today-count").textContent = today.total_count;
    document.getElementById("stat-today-weight").textContent = formatGrams(today.total_weight_g);
    return all;
  }

  function renderCategoryCharts(summary) {
    const labels = summary.per_category.map((r) => nameBySlug[r.category] || r.category);
    const colors = summary.per_category.map((r) => colorBySlug[r.category] || "#888");
    const weights = summary.per_category.map((r) => r.weight_g);
    const counts = summary.per_category.map((r) => r.count);

    new Chart(document.getElementById("chart-weight-cat"), {
      type: "doughnut",
      data: { labels, datasets: [{ data: weights, backgroundColor: colors }] },
      options: { responsive: true },
    });

    new Chart(document.getElementById("chart-count-cat"), {
      type: "bar",
      data: { labels, datasets: [{ label: "Items", data: counts, backgroundColor: colors }] },
      options: { responsive: true, plugins: { legend: { display: false } } },
    });
  }

  async function renderHourly() {
    const hourly = await fetchJSON("/api/hourly?hours=24");
    new Chart(document.getElementById("chart-daily"), {
      type: "line",
      data: {
        labels: hourly.map((d) => d.hour),
        datasets: [
          { label: "Weight (g)", data: hourly.map((d) => d.weight_g), borderColor: "#047857", tension: 0.25, fill: false },
          { label: "Items", data: hourly.map((d) => d.count), borderColor: "#f59e0b", tension: 0.25, fill: false, yAxisID: "y1" },
        ],
      },
      options: {
        responsive: true,
        scales: {
          x: { title: { display: true, text: "Hour (UTC)" } },
          y: { position: "left", title: { display: true, text: "Weight (g)" }, beginAtZero: true },
          y1: { position: "right", title: { display: true, text: "Items" }, beginAtZero: true, grid: { drawOnChartArea: false } },
        },
      },
    });
  }

  (async () => {
    try {
      const all = await loadStats();
      renderCategoryCharts(all);
      await renderHourly();
    } catch (err) {
      console.error("analytics load failed", err);
    }
  })();
})();
