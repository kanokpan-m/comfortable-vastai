// Comfortable inside ComfyUI: a "Comfortable" sidebar tab with the dashboard, an automatic
// check of every workflow you open, and the auto-stop warning.
import { app } from "../../scripts/app.js";

// The sidebar icon is the Comfortable logo (shipped next to this file), drawn by a CSS class.
const LOGO = new URL("./logo.png", import.meta.url).href;
const iconStyle = document.createElement("style");
iconStyle.textContent = `.comfortable-icon{display:inline-block;width:1.4rem;height:1.4rem;background:url("${LOGO}") center/contain no-repeat}`;
document.head.appendChild(iconStyle);

const BASE = "/comfortable/";
const state = { count: 0, plan: null, frame: null, timer: null, banner: null };

function currentWorkflow() {
  try { return app.graph.serialize(); } catch { return null; }
}

function post(msg) {
  state.frame?.contentWindow?.postMessage(msg, location.origin);
}

async function analyze(missingNodes = []) {
  const workflow = currentWorkflow();
  if (!workflow || !workflow.nodes?.length) return;
  try {
    const res = await fetch(`${BASE}api/fix/plan`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workflow, missing_nodes: missingNodes }),
    });
    if (!res.ok) return;
    const plan = await res.json();
    state.plan = plan;
    const s = plan.summary;
    state.count = s.models_missing + s.nodes_missing;
    post({ type: "comfortable:plan", plan });
    if (state.count) {
      const fixable = s.models_fixable + s.nodes_fixable;
      app.extensionManager?.toast?.add({
        severity: "warn", summary: "Comfortable",
        detail: `${state.count} missing item(s) in this workflow` + (fixable ? `, ${fixable} can be fixed automatically` : "") + ". Open the Comfortable tab.",
        life: 9000,
      });
    }
  } catch (e) {
    console.warn("[Comfortable] workflow check failed", e);
  }
}

function scheduleAnalyze(missing) {
  clearTimeout(state.timer);
  state.timer = setTimeout(() => analyze(missing), 600);
}

// Messages from the dashboard iframe.
window.addEventListener("message", async (e) => {
  if (e.origin !== location.origin || !e.data?.type?.startsWith("comfortable:")) return;
  const { type } = e.data;
  if (type === "comfortable:get-workflow") {
    post({ type: "comfortable:workflow", workflow: currentWorkflow(), name: app.extensionManager?.workflow?.activeWorkflow?.filename || "Current workflow" });
    if (state.plan) post({ type: "comfortable:plan", plan: state.plan });
  } else if (type === "comfortable:refresh-models") {
    try { await app.refreshComboInNodes(); } catch (err) { console.warn("[Comfortable] refresh failed", err); }
    scheduleAnalyze([]);
  } else if (type === "comfortable:reanalyze") {
    scheduleAnalyze([]);
  } else if (type === "comfortable:reload") {
    // After new node packs: ComfyUI was restarted, reload so their nodes and UI appear.
    location.reload();
  } else if (type === "comfortable:open-workflow") {
    // A starter workflow from the Workflows screen: open it in a new workflow tab.
    await openWorkflow(e.data.workflow, e.data.name);
  }
});

async function openWorkflow(graph, name) {
  if (!graph) return;
  try {
    await app.loadGraphData(graph, true, true, name || "Comfortable starter");
    app.extensionManager?.toast?.add({ severity: "success", summary: "Comfortable", detail: `Opened ${name || "the workflow"}`, life: 4000 });
  } catch (err) {
    console.warn("[Comfortable] could not open the workflow", err);
    app.extensionManager?.toast?.add({ severity: "error", summary: "Comfortable", detail: `Couldn't open ${name || "the workflow"}: ${err}`, life: 9000 });
  }
}

// Opened from the dashboard as <ComfyUI>/?comfortable_open=<workflow id>: load that starter workflow
// once ComfyUI has restored its own tabs, then drop the parameter so a reload doesn't open it again.
async function openFromUrl() {
  const params = new URLSearchParams(location.search);
  const id = params.get("comfortable_open");
  if (!id) return;
  params.delete("comfortable_open");
  history.replaceState(null, "", location.pathname + (params.toString() ? `?${params}` : "") + location.hash);
  try {
    const res = await fetch(`${BASE}api/catalog/workflows/${encodeURIComponent(id)}`);
    if (!res.ok) throw new Error(`${res.status}`);
    const wf = await res.json();
    await new Promise((r) => setTimeout(r, 1500));
    await openWorkflow(wf.graph, wf.title);
  } catch (err) {
    console.warn("[Comfortable] starter workflow not found", id, err);
  }
}

// Auto-stop warning, shown over ComfyUI.
function showBanner(status) {
  if (!status?.warned && !status?.stopping) return hideBanner();
  if (!state.banner) {
    const b = document.createElement("div");
    b.style.cssText = "position:fixed;top:56px;left:50%;transform:translateX(-50%);z-index:10000;display:flex;gap:12px;align-items:center;"
      + "background:#171718;color:#fff;border:1px solid #fd9903;border-radius:10px;padding:10px 14px;font:13px Inter,system-ui,sans-serif;box-shadow:0 8px 30px #0008";
    b.innerHTML = `<span id="comfortable-stop-text"></span><button style="background:#0b8ce9;color:#fff;border:0;border-radius:6px;padding:6px 10px;cursor:pointer;font:inherit">Keep running</button>`;
    b.querySelector("button").onclick = () => fetch(`${BASE}api/autostop/snooze`, { method: "POST" }).then(hideBanner);
    document.body.appendChild(b);
    state.banner = b;
  }
  const mins = Math.max(1, Math.round((status.stops_in || 0) / 60));
  state.banner.querySelector("#comfortable-stop-text").textContent = status.stopping
    ? "Instance is idle and stopping now…"
    : `Instance idle: it will stop in about ${mins} min to save money.`;
}
function hideBanner() { state.banner?.remove(); state.banner = null; }

function listen() {
  const es = new EventSource(`${BASE}api/events`);
  es.addEventListener("autostop", (e) => showBanner(JSON.parse(e.data)));
}

app.registerExtension({
  name: "comfortable",
  async setup() {
    app.extensionManager.registerSidebarTab({
      id: "comfortable",
      icon: "comfortable-icon",
      title: "Comfortable",
      tooltip: "Comfortable: fix missing models and nodes, library, downloads",
      iconBadge: () => (state.count ? String(state.count) : null),
      type: "custom",
      render(el) {
        // Keep one iframe alive so the dashboard keeps its state between tab switches.
        if (!state.frame) {
          state.frame = document.createElement("iframe");
          state.frame.src = `${BASE}?embed=1#/fix`;
          state.frame.title = "Comfortable";
          state.frame.style.cssText = "width:100%;height:100%;border:0;display:block;background:#171718";
        }
        el.style.height = "100%";
        el.appendChild(state.frame);
      },
    });
    listen();
    openFromUrl();
  },
  async afterConfigureGraph(missingNodeTypes) {
    const missing = (missingNodeTypes || []).map((m) => (typeof m === "string" ? m : m?.type)).filter(Boolean);
    scheduleAnalyze(missing);
  },
});
