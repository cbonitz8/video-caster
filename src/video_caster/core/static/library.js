import { h } from "./dom.js";
import { formatLeft } from "./util.js";
import { browseBack, call, openBrowse, tapFile } from "./actions.js";
import { nowPlaying, update } from "./store.js";

function fileRow(row, meta, live) {
  return h("button", { class: "row", type: "button", disabled: !live, onclick: () => tapFile(row) },
    h("span", { class: "row-title" }, row.title),
    row.subtitle === null ? null : h("span", { class: "row-sub" }, row.subtitle),
    meta,
  );
}

function folderRow(label, folder, live) {
  return h("button", { class: "row", type: "button", disabled: !live, onclick: () => openBrowse(folder) },
    h("span", { class: "row-title" }, label));
}

function section(title, rows) {
  if (rows.length === 0) return null;
  return h("div", {}, h("h2", { class: "section-head" }, title), rows);
}

function progressMeta(row) {
  if (row.duration <= 0) return null;
  return [
    h("div", { class: "bar" }, h("span", { style: `width:${Math.round(row.progress * 100)}%` })),
    h("span", { class: "row-meta" }, formatLeft(row.position, row.duration)),
  ];
}

function upNextMeta(row) {
  const watched = row.watched.subtitle === null ? row.watched.title : row.watched.subtitle;
  return h("span", { class: "row-meta" }, `after ${watched}`);
}

function home(library, live) {
  return h("div", {},
    section("Continue Watching", library.continue_watching.map((r) => fileRow(r, progressMeta(r), live))),
    section("Up Next", library.up_next.map((r) => fileRow(r, upNextMeta(r), live))),
    section("Newly Added", library.newly_added.map((r) =>
      fileRow(r, h("span", { class: "row-meta" }, r.mtime_ago), live))),
    h("h2", { class: "section-head" }, "Everything"),
    folderRow("Browse folders", { path: null, name: "Folders" }, live),
  );
}

function browse(state, live) {
  const { stack, entries, error } = state.browse;
  const head = h("div", { class: "browse-head" },
    h("button", { class: "back", type: "button", "aria-label": "Back", onclick: browseBack }, "‹"),
    h("h2", { class: "section-head" }, stack[stack.length - 1].name));
  if (error !== null) return h("div", {}, head, h("p", { class: "empty" }, "Couldn't open this folder."));
  if (entries === null) return h("div", {}, head, h("p", { class: "empty" }, "Loading…"));
  if (entries.length === 0) return h("div", {}, head, h("p", { class: "empty" }, "No videos here."));
  return h("div", {}, head, entries.map((e) => (e.is_dir
    ? folderRow(`📁 ${e.name}`, { path: e.path, name: e.name }, live)
    : fileRow(e, null, live))));
}

export function renderLibrary(state) {
  const live = state.conn === "live";
  if (state.browse !== null) return browse(state, live);
  if (state.library === null) return h("p", { class: "empty" }, "Loading…");
  return home(state.library, live);
}

export function createNowBar(el) {
  const title = h("span", { class: "row-title" });
  const sub = h("span", { class: "row-sub" });
  const text = h("button", { class: "nowbar-text", type: "button", onclick: () => update({ tab: "remote" }) }, title, sub);
  const toggle = h("button", {
    class: "icon-btn", type: "button", "aria-label": "Play or pause",
    onclick: () => call("/api/playback/toggle"),
  });
  el.replaceChildren(text, toggle);

  return {
    patch(state) {
      const now = nowPlaying(state);
      el.hidden = state.tab !== "library" || now.kind === "idle";
      if (el.hidden) return;
      if (now.kind === "starting") {
        title.textContent = now.title;
        const slow = now.since !== null && Date.now() - now.since > 30000;
        sub.textContent = slow ? "Still starting… (TV may be busy)" : "Starting…";
        toggle.hidden = true;
        return;
      }
      const { current } = now;
      title.textContent = current.title;
      sub.textContent = current.subtitle === null ? "" : current.subtitle;
      toggle.hidden = false;
      toggle.textContent = state.server.status.state === "playing" ? "⏸" : "▶";
      toggle.disabled = state.conn !== "live";
    },
  };
}
