import { h } from "./dom.js";
import { episodeParts, findShow } from "./util.js";
import { browseBack, call, openBrowse, tapFile } from "./actions.js";
import { nowPlaying, update } from "./store.js";
import { count, renderShelves } from "./shelves.js";
import { renderShow } from "./showpage.js";

function subtitleLine(subtitle) {
  const parts = episodeParts(subtitle);
  if (parts === null) return h("span", { class: "mga-row__sub" }, subtitle);
  return h("span", { class: "mga-row__sub" },
    h("span", { class: "mga-row__code" }, parts.code),
    parts.name === null ? null : ` · ${parts.name}`);
}

function fileRow(row, extra, meta, live) {
  return h("button", { class: "mga-row", type: "button", disabled: !live, onclick: () => tapFile(row) },
    h("span", { class: "mga-row__text" },
      h("span", { class: "mga-row__title" }, row.title),
      row.subtitle === null ? null : subtitleLine(row.subtitle),
      extra),
    h("span", { class: "mga-row__meta" }, meta));
}

function folderRow(label, folder, live) {
  return h("button", { class: "mga-row", type: "button", disabled: !live, onclick: () => openBrowse(folder) },
    h("span", { class: "mga-row__text" }, h("span", { class: "mga-row__title mga-row__folder" }, label)),
    h("span", { class: "mga-row__meta" }, "▸"));
}

function home(library, live) {
  return h("div", { class: "lib" },
    renderShelves(library, live),
    h("section", { class: "lib-section" },
      h("h2", { class: "mga-sectionbar" }, "Everything"),
      h("div", { class: "mga-list" }, folderRow("Browse folders", { path: null, name: "Folders" }, live))),
  );
}

function empty(text) {
  return h("p", { class: "empty mga-halftone" }, text);
}

function browse(state, live) {
  const { stack, entries, error } = state.browse;
  const head = h("div", { class: "browse-bar" },
    h("button", { class: "browse-back", type: "button", "aria-label": "Back", onclick: browseBack }, "◀"),
    h("h2", { class: "mga-sectionbar browse-title" }, stack[stack.length - 1].name,
      entries === null ? null : count(entries.length)));
  if (error !== null) return h("div", { class: "lib-section" }, head, empty("Couldn't open this folder."));
  if (entries === null) return h("div", { class: "lib-section" }, head, empty("Loading…"));
  if (entries.length === 0) return h("div", { class: "lib-section" }, head, empty("No videos here."));
  return h("div", { class: "lib-section" }, head, h("div", { class: "mga-list" }, entries.map((e) => (e.is_dir
    ? folderRow(e.name, { path: e.path, name: e.name }, live)
    : fileRow(e, null, "", live)))));
}

export function renderLibrary(state) {
  const live = state.conn === "live";
  if (state.browse !== null) return browse(state, live);
  if (state.library === null) return empty("Loading…");
  const show = state.show === null ? null : findShow(state.library, state.show);
  if (show !== null) return renderShow(show, live);
  return home(state.library, live);
}

export function createNowBar(el) {
  const label = h("span", { class: "nowbar-label" });
  const title = h("span", { class: "nowbar-title" });
  const text = h("button", { class: "nowbar-text", type: "button", onclick: () => update({ tab: "remote" }) }, label, title);
  const toggle = h("button", {
    class: "nowbar-toggle", type: "button", "aria-label": "Play or pause",
    onclick: () => call("/api/playback/toggle"),
  });
  el.replaceChildren(text, toggle);

  return {
    patch(state) {
      const now = nowPlaying(state);
      el.hidden = state.tab !== "library" || now.kind === "idle";
      if (el.hidden) return;
      if (now.kind === "starting") {
        const slow = now.since !== null && Date.now() - now.since > 30000;
        label.textContent = slow ? "Still starting… TV may be busy" : "Starting…";
        title.textContent = now.title;
        toggle.hidden = true;
        return;
      }
      const { current } = now;
      label.textContent = current.subtitle === null ? "Now playing" : `Now playing · ${current.subtitle}`;
      title.textContent = current.title;
      toggle.hidden = false;
      toggle.textContent = state.server.status.state === "playing" ? "❚❚" : "▶";
      toggle.disabled = state.conn !== "live";
    },
  };
}
