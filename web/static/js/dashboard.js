const API = "";
const CLIENT = window.__DASHBOARD_CLIENT__ || "eli_lilly";

const charts = {};

function formatApiError(data, fallback) {
  const d = data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join("; ");
  return fallback || "Request failed";
}

let companyName = "Company";

function fmtPct(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  return `${v}%`;
}

function seriesForChart(arr) {
  return (arr || []).map((v) => (v === null || v === undefined ? NaN : Number(v)));
}

function showDashboardError(msg) {
  const el = document.getElementById("dashboard-error");
  if (!el) return;
  if (msg) {
    el.textContent = msg;
    el.classList.remove("hidden");
  } else {
    el.textContent = "";
    el.classList.add("hidden");
  }
}

function trendHtml(delta) {
  if (delta == null) return "";
  const cls = delta >= 0 ? "trend-up" : "trend-down";
  const arrow = delta >= 0 ? "▲" : "▼";
  return `<span class="${cls}">${arrow} ${Math.abs(delta)} pts vs prior</span>`;
}


function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}


function applyCompanyLabels(name) {
  companyName = name || "Company";
  document.getElementById("dashboard-title")?.replaceChildren(
    document.createTextNode(`${companyName} — GLP-1 AI visibility`)
  );
  document.getElementById("dashboard-subtitle")?.replaceChildren(
    document.createTextNode(
      `Each question on the platform adds a data point for ${companyName}`
    )
  );
  const sovH = document.getElementById("chart-sov-title");
  if (sovH) sovH.textContent = `${companyName} share of voice`;
  const visH = document.getElementById("chart-vis-title");
  if (visH) visH.textContent = `${companyName} visibility rate`;
  const brandTh = document.getElementById("th-brand-mentions");
  if (brandTh) brandTh.textContent = `${companyName} mentions`;
}

function destroyChart(id) {
  if (charts[id]) {
    charts[id].destroy();
    delete charts[id];
  }
}

function baseChartOptions(yTitle, yMax = null) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: { legend: { position: "bottom" } },
    scales: {
      x: {
        ticks: { maxRotation: 45, minRotation: 0, font: { size: 10 } },
      },
      y: {
        beginAtZero: true,
        max: yMax ?? undefined,
        title: { display: true, text: yTitle },
      },
    },
  };
}

function buildLineChart(canvasId, labels, datasets, yTitle, yMax = 100) {
  destroyChart(canvasId);
  const el = document.getElementById(canvasId);
  if (!el || typeof Chart === "undefined") {
    showDashboardError(
      typeof Chart === "undefined"
        ? "Charts could not load (Chart.js blocked?). KPI numbers below should still update."
        : null
    );
    return;
  }
  const normalized = datasets.map((ds) => ({
    ...ds,
    data: seriesForChart(ds.data),
  }));
  try {
    charts[canvasId] = new Chart(el, {
      type: "line",
      data: { labels, datasets: normalized },
      options: baseChartOptions(yTitle, yMax),
    });
  } catch (err) {
    console.error("Chart render failed", canvasId, err);
  }
}

function renderDashboard(data) {
  if (!data) return;
  if (data.error) showDashboardError(`Server: ${data.error}`);
  else showDashboardError(null);

  const runs = data.runs || [];
  if (data.company_name) applyCompanyLabels(data.company_name);
  populateKpis(data);
  populateTable(runs);

  const hint = document.getElementById("no-data-hint");
  if (!data.labels?.length) {
    hint?.classList.remove("hidden");
    Object.keys(charts).forEach((id) => destroyChart(id));
    return;
  }
  hint?.classList.add("hidden");
  populateCharts(data);
}

function populateKpis(data) {
  const s = data.summary || {};
  const sovEl = document.getElementById("kpi-sov");
  if (!sovEl) return;
  sovEl.textContent = fmtPct(s.latest_sov);
  document.getElementById("kpi-sov-sub").innerHTML =
    `10-question avg: ${fmtPct(s.avg_sov_10)} ${trendHtml(s.trend_sov)}`;
  document.getElementById("kpi-visibility").textContent = fmtPct(s.latest_visibility);
  document.getElementById("kpi-visibility-sub").textContent = `10-question avg: ${fmtPct(s.avg_visibility_10)}`;
  document.getElementById("kpi-favorable-rate").textContent = fmtPct(s.latest_favorable_rate);
  document.getElementById("kpi-favorable-sub").textContent = `10-question avg: ${fmtPct(s.avg_favorable_10)}`;
  document.getElementById("kpi-fav-index").textContent =
    s.latest_favorability_index != null ? s.latest_favorability_index : "—";
  const tone = s.latest_favorability ? `Last tone: ${s.latest_favorability}` : "";
  document.getElementById("kpi-fav-index-sub").textContent = tone || "Tone score 0–100";
  document.getElementById("kpi-chat").textContent = data.chat_questions ?? 0;
  document.getElementById("kpi-runs").textContent = s.total_snapshots ?? 0;
  document.getElementById("kpi-runs-sub").textContent =
    `${data.chat_questions ?? 0} chat · ${data.audit_runs ?? 0} audit batteries`;
}

function populateTable(runs) {
  const tbody = document.querySelector("#runs-tbody");
  if (!tbody) return;
  tbody.innerHTML = "";
  runs.forEach((r) => {
    const type = r.platform === "chat" ? "Chat" : `Audit (${r.total_prompts})`;
    const preview = escapeHtml(r.prompt_preview || "—");
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.created_at?.slice(0, 19).replace("T", " ")}</td>
      <td>${type}</td>
      <td title="${preview}">${preview}</td>
      <td>${fmtPct(r.share_of_voice_pct)}</td>
      <td>${fmtPct(r.visibility_pct)}</td>
      <td>${fmtPct(r.favorable_rate_pct)}</td>
      <td>${r.favorability_index ?? "—"}</td>
      <td>${r.brand_mention_total}</td>
      <td>${r.competitor_mention_total}</td>
    `;
    tbody.appendChild(tr);
  });
}

function populateCharts(data) {
  const labels = data.labels || [];
  if (!labels.length) return;

  const rollingSov = {
    label: "5-question avg SOV",
    data: data.rolling_sov_5 || [],
    borderColor: "#94a3b8",
    borderDash: [6, 4],
    tension: 0.3,
    spanGaps: true,
  };

  buildLineChart(
    "chart-sov",
    labels,
    [
      {
        label: "Share of voice (%)",
        data: data.share_of_voice_pct,
        borderColor: "#e85d04",
        backgroundColor: "rgba(232, 93, 4, 0.12)",
        fill: true,
        tension: 0.3,
      },
      rollingSov,
    ],
    "Percent",
    100
  );

  buildLineChart(
    "chart-visibility",
    labels,
    [
      {
        label: "Visibility (%)",
        data: data.visibility_pct,
        borderColor: "#2563eb",
        backgroundColor: "rgba(37, 99, 235, 0.1)",
        fill: true,
        tension: 0.3,
      },
      {
        label: "5-question avg",
        data: data.rolling_visibility_5 || [],
        borderColor: "#94a3b8",
        borderDash: [6, 4],
        tension: 0.3,
        spanGaps: true,
      },
    ],
    "Percent",
    100
  );

  buildLineChart(
    "chart-favorable",
    labels,
    [
      {
        label: "Favorable rate (%)",
        data: data.favorable_rate_pct,
        borderColor: "#16a34a",
        backgroundColor: "rgba(22, 163, 74, 0.1)",
        fill: true,
        tension: 0.3,
      },
      {
        label: "5-question avg",
        data: data.rolling_favorable_5 || [],
        borderColor: "#94a3b8",
        borderDash: [6, 4],
        tension: 0.3,
        spanGaps: true,
      },
    ],
    "Percent",
    100
  );

  buildLineChart(
    "chart-index",
    labels,
    [
      {
        label: "Favorability index",
        data: data.favorability_index,
        borderColor: "#7c3aed",
        backgroundColor: "rgba(124, 58, 237, 0.1)",
        fill: true,
        tension: 0.3,
      },
    ],
    "Score",
    100
  );
}

async function fetchDashboardData() {
  const res = await fetch(`${API}/api/audit/history?client_id=${CLIENT}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(formatApiError(err, res.statusText));
  }
  return res.json();
}

async function loadDashboard() {
  try {
    const data = await fetchDashboardData();
    renderDashboard(data);
  } catch (e) {
    showDashboardError(
      `Could not refresh dashboard: ${e.message}. Showing last loaded data if available.`
    );
    if (window.__DASHBOARD_BOOT__) renderDashboard(window.__DASHBOARD_BOOT__);
  }
}

document.getElementById("btn-run-audit")?.addEventListener("click", async () => {
  const btn = document.getElementById("btn-run-audit");
  btn.disabled = true;
  btn.textContent = "Running audit…";
  try {
    const res = await fetch(`${API}/api/audit/run?client_id=${CLIENT}`, { method: "POST" });
    const errBody = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(formatApiError(errBody, res.statusText));
    await loadDashboard();
  } catch (e) {
    alert(`Audit failed: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Run audit now";
  }
});

if (window.__DASHBOARD_BOOT__) {
  renderDashboard(window.__DASHBOARD_BOOT__);
}
loadDashboard();

setInterval(loadDashboard, 15000);
