const API = "";
const CLIENT = "eli_lilly";

function showToast(message, duration = 2200) {
  const toast = document.getElementById("toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toast._hideTimer);
  toast._hideTimer = setTimeout(() => toast.classList.remove("visible"), duration);
}

function formatApiError(data, fallback) {
  const d = data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x.msg || JSON.stringify(x)).join("; ");
  return fallback || "Request failed";
}
let visitId = null;
let placement = { company_name: "", enabled: true, drugs: [] };
let pendingAttachment = null;

const chatEl = document.getElementById("chat");
const composer = document.getElementById("composer-input");
const emptyState = document.getElementById("empty-state");

const SUGGESTIONS = [
  "Compare tirzepatide versus semaglutide for weight loss in adults with obesity.",
  "What is the best first-line GLP-1 for type 2 diabetes with obesity?",
  "How does SELECT inform anticoagulation-risk patients choosing Wegovy?",
  "SURPASS-2 results: tirzepatide vs semaglutide 1 mg for A1c and weight?",
];

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function linkCitations(html, sources) {
  return html.replace(/\[(\d+(?:-\d+)?)\]/g, (match, num) => {
    const n = num.split("-")[0];
    const src = sources.find((s) => String(s.index) === n);
    const title = src ? escapeHtml(src.title) : "Source";
    return `<a class="cite" href="#source-${n}" title="${title}">${match}</a>`;
  });
}

function markdownLite(text) {
  let html = escapeHtml(text);
  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\n\n/g, "</p><p>");
  html = `<p>${html}</p>`;
  return html;
}

function renderSources(sources) {
  if (!sources?.length) return "";
  const items = sources
    .map(
      (s) => `
    <div class="source-item" id="source-${s.index}">
      <span class="idx">[${s.index}]</span>
      ${escapeHtml(s.title)}
      ${s.pmid ? ` — <a href="${s.url}" target="_blank" rel="noopener">PMID ${s.pmid}</a>` : ""}
    </div>`
    )
    .join("");
  return `<div class="sources-panel"><h4>References</h4>${items}</div>`;
}

function renderDiscoveredDrugs() {
  const el = document.getElementById("discovered-drugs");
  if (!el) return;
  if (!placement.drugs?.length) {
    el.innerHTML = "<p class='drug-empty'>No drugs loaded yet.</p>";
    return;
  }
  el.innerHTML =
    "<p class='drug-list-title'>Prioritized in answers:</p><ul>" +
    placement.drugs
      .map(
        (d, i) =>
          `<li><span class="drug-rank">${i + 1}</span> <strong>${escapeHtml(d.brand)}</strong>${
            d.generic ? ` <span class="drug-gen">(${escapeHtml(d.generic)})</span>` : ""
          }</li>`
      )
      .join("") +
    "</ul>";
}

function clearCompanyInput() {
  const input = document.getElementById("company-name");
  if (input) input.value = "";
}

async function resetPlacementOnLoad() {
  try {
    const res = await fetch(`${API}/api/placement/clear?client_id=${CLIENT}`, {
      method: "POST",
    });
    if (res.ok) placement = await res.json();
    else placement = { company_name: "", enabled: true, drugs: [] };
  } catch {
    placement = { company_name: "", enabled: true, drugs: [] };
  }
  clearCompanyInput();
  const enabled = document.getElementById("placement-enabled");
  if (enabled) enabled.checked = placement.enabled !== false;
  renderDiscoveredDrugs();
}

async function discoverCompany() {
  const company = document.getElementById("company-name")?.value?.trim();
  if (!company) {
    alert("Enter a company name first");
    return;
  }
  const btn = document.getElementById("btn-discover");
  const st = document.getElementById("placement-status");
  btn.disabled = true;
  btn.textContent = "Researching…";
  st.textContent = "Querying openFDA and GLP-1 portfolio data…";
  try {
    const res = await fetch(`${API}/api/company/discover`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        company_name: company,
        client_id: CLIENT,
        enabled: document.getElementById("placement-enabled").checked,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(formatApiError(data, res.statusText));
    placement = data.placement;
    renderDiscoveredDrugs();
    st.textContent = data.message || "Placement applied.";
  } catch (e) {
    st.textContent = "";
    alert(e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Discover drugs & apply";
  }
}

function appendMessage(role, content, meta = {}) {
  emptyState?.classList.add("hidden");
  const wrap = document.createElement("div");
  wrap.className = "message-block";

  if (role === "user") {
    wrap.innerHTML = `<div class="query-bubble">${escapeHtml(content)}</div>`;
  } else {
    const body = linkCitations(markdownLite(content), meta.sources || []);
    wrap.innerHTML = `
      <div class="status-row done">Finished thinking</div>
      <div class="answer-body">${body}</div>
      ${renderSources(meta.sources)}
    `;
  }
  chatEl.appendChild(wrap);
  chatEl.parentElement.scrollTop = chatEl.parentElement.scrollHeight;
  return wrap;
}

function beginAssistantStream() {
  emptyState?.classList.add("hidden");
  const wrap = document.createElement("div");
  wrap.className = "message-block";
  wrap.innerHTML = `
    <div class="status-row thinking">Thinking</div>
    <div class="answer-body streaming"></div>
  `;
  chatEl.appendChild(wrap);
  const statusEl = wrap.querySelector(".status-row");
  const bodyEl = wrap.querySelector(".answer-body");
  return { wrap, statusEl, bodyEl };
}

function updateAssistantStream(bodyEl, statusEl, text, sources) {
  bodyEl.textContent = text;
  if (statusEl) {
    statusEl.className = "status-row thinking";
    statusEl.textContent = "Writing";
  }
  chatEl.parentElement.scrollTop = chatEl.parentElement.scrollHeight;
}

function finishAssistantStream(wrap, statusEl, bodyEl, text, sources) {
  if (statusEl) {
    statusEl.className = "status-row done";
    statusEl.textContent = "Finished thinking";
  }
  bodyEl.classList.remove("streaming");
  bodyEl.innerHTML = linkCitations(markdownLite(text), sources || []);
  wrap.insertAdjacentHTML("beforeend", renderSources(sources));
  chatEl.parentElement.scrollTop = chatEl.parentElement.scrollHeight;
}

async function ensureVisit() {
  if (visitId) return visitId;
  const res = await fetch(`${API}/api/visits`, { method: "POST" });
  const data = await res.json();
  visitId = data.visit_id;
  return visitId;
}

function parseSseChunk(buffer) {
  const events = [];
  const parts = buffer.split("\n\n");
  const rest = parts.pop() || "";
  for (const part of parts) {
    const line = part.split("\n").find((l) => l.startsWith("data: "));
    if (!line) continue;
    try {
      events.push(JSON.parse(line.slice(6)));
    } catch (_) {}
  }
  return { events, rest };
}

function clearAttachment() {
  pendingAttachment = null;
  const badge = document.getElementById("attachment-badge");
  if (badge) {
    badge.innerHTML = "";
    badge.classList.add("hidden");
  }
}

function renderAttachmentBadge() {
  const badge = document.getElementById("attachment-badge");
  if (!badge || !pendingAttachment) return;
  badge.classList.remove("hidden");
  badge.innerHTML = `
    <span class="attachment-badge-pill">
      📎 ${escapeHtml(pendingAttachment.name)}
      <button title="Remove attachment" onclick="clearAttachment()">✕</button>
    </span>`;
}

async function ask(question) {
  if (!question.trim()) return;

  let fullQuestion = question;
  if (pendingAttachment) {
    fullQuestion = `${question}\n\n[Attached file: ${pendingAttachment.name}]\n${pendingAttachment.content}`;
    appendMessage("user", `${question} 📎 ${pendingAttachment.name}`);
    clearAttachment();
  } else {
    appendMessage("user", question);
  }
  composer.value = "";

  const { wrap, statusEl, bodyEl } = beginAssistantStream();

  try {
    const vid = await ensureVisit();
    const res = await fetch(`${API}/api/ask/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: fullQuestion,
        visit_id: vid,
        client_id: CLIENT,
        use_placement: document.getElementById("placement-enabled")?.checked ?? true,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      wrap.remove();
      appendMessage("assistant", `Error: ${formatApiError(err, res.statusText)}`);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let answer = "";
    let sources = [];

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const { events, rest } = parseSseChunk(buffer);
      buffer = rest;
      for (const ev of events) {
        if (ev.type === "token" && ev.content) {
          answer += ev.content;
          updateAssistantStream(bodyEl, statusEl, answer, sources);
        } else if (ev.type === "done") {
          visitId = ev.visit_id || visitId;
          sources = ev.sources || [];
          if (ev.placement) {
            placement = ev.placement;
            renderDiscoveredDrugs();
          }
        } else if (ev.type === "error") {
          throw new Error(ev.message || "Stream failed");
        }
      }
    }

    finishAssistantStream(wrap, statusEl, bodyEl, answer, sources);
  } catch (e) {
    wrap.remove();
    appendMessage("assistant", `Could not reach server. Is Ollama running? (${e.message})`);
  }
}

document.getElementById("btn-send")?.addEventListener("click", () => ask(composer.value));
document.getElementById("btn-discover")?.addEventListener("click", discoverCompany);

document.getElementById("btn-new-visit")?.addEventListener("click", () => {
  visitId = null;
  chatEl.innerHTML = "";
  clearAttachment();
  emptyState?.classList.remove("hidden");
  ensureVisit();
  showToast("New visit started");
});

document.getElementById("btn-share")?.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(window.location.href);
    showToast("Link copied to clipboard");
  } catch {
    const url = window.location.href;
    prompt("Copy this link:", url);
  }
});

document.getElementById("btn-attach")?.addEventListener("click", () => {
  document.getElementById("file-input")?.click();
});

document.getElementById("file-input")?.addEventListener("change", (e) => {
  const file = e.target.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (ev) => {
    const content = ev.target.result;
    pendingAttachment = {
      name: file.name,
      content: typeof content === "string" ? content.slice(0, 8000) : "",
    };
    renderAttachmentBadge();
    showToast(`Attached: ${file.name}`);
  };
  reader.readAsText(file);
  e.target.value = "";
});

composer?.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    ask(composer.value);
  }
});

const sugEl = document.getElementById("suggestions");
SUGGESTIONS.forEach((q) => {
  const b = document.createElement("button");
  b.textContent = q;
  b.addEventListener("click", () => ask(q));
  sugEl?.appendChild(b);
});

async function checkHealth() {
  try {
    const res = await fetch(`${API}/api/health`);
    const h = await res.json();
    const st = document.getElementById("placement-status");
    if (!h.ollama && st) {
      st.textContent = "Ollama offline — start Ollama and run: ollama pull llama3.2";
      st.style.color = "#b45309";
    } else if (!h.ollama_model_ready && st) {
      st.textContent = `Pull model: ollama pull ${h.model || "llama3.2"}`;
      st.style.color = "#b45309";
    }
  } catch (_) {}
}

resetPlacementOnLoad().then(() => {
  checkHealth();
  ensureVisit();
});
