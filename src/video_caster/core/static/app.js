import { connect } from "./api.js";
import { dispatch, getState, subscribe, update } from "./store.js";
import { createNowBar, renderLibrary } from "./library.js";
import { createRemote } from "./remote.js";
import { renderSheet } from "./sheets.js";
import { refreshLibrary } from "./actions.js";

const $ = (id) => document.getElementById(id);
const nowBar = createNowBar($("nowbar"));
const remote = createRemote($("remote-tab"));
let prev = null;
let toastTimer = null;
let refreshQueued = false;

function deviceLabel(server) {
  if (server === null) return "…";
  const selected = server.devices.find((d) => d.id === server.selected_device);
  return selected === undefined ? "No device" : selected.name;
}

function sheetChanged(s, p) {
  if (p === null || s.sheet !== p.sheet || s.conn !== p.conn) return true;
  if (s.sheet === null || s.sheet.kind !== "devices") return false;
  return s.server.devices !== p.server.devices
    || s.server.selected_device !== p.server.selected_device
    || s.server.scan !== p.server.scan
    || s.server.pending !== p.server.pending;
}

function render(s) {
  $("strip").hidden = s.conn === "live";
  const chip = $("device-chip");
  chip.textContent = deviceLabel(s.server);
  chip.disabled = s.server === null || s.conn !== "live";
  for (const btn of document.querySelectorAll("[data-tab]")) {
    btn.classList.toggle("active", btn.dataset.tab === s.tab);
  }
  $("library-tab").hidden = s.tab !== "library";
  $("remote-tab").hidden = s.tab !== "remote";
  if (prev === null || s.library !== prev.library || s.browse !== prev.browse || s.conn !== prev.conn) {
    $("library-tab").replaceChildren(renderLibrary(s));
  }
  nowBar.patch(s);
  remote.patch(s);
  if (sheetChanged(s, prev)) renderSheet($("sheet-layer"), s);
  if (prev === null || s.toast !== prev.toast) {
    $("toast").hidden = s.toast === null;
    $("toast").textContent = s.toast === null ? "" : s.toast.message;
    clearTimeout(toastTimer);
    if (s.toast !== null) toastTimer = setTimeout(() => update({ toast: null }), 4000);
  }
  if (s.libraryStale && s.conn === "live" && !refreshQueued) {
    refreshQueued = true;
    queueMicrotask(() => {
      refreshQueued = false;
      refreshLibrary();
    });
  }
  prev = s;
}

for (const btn of document.querySelectorAll("[data-tab]")) {
  btn.addEventListener("click", () => {
    const tab = btn.dataset.tab;
    update(tab === "library" ? { tab, libraryStale: true } : { tab });
  });
}
$("device-chip").addEventListener("click", () => update({ sheet: { kind: "devices" } }));
$("toast").addEventListener("click", () => update({ toast: null }));
setInterval(() => nowBar.patch(getState()), 5000);

subscribe(render);
render(getState());
connect(dispatch, (conn) => update({ conn }));
