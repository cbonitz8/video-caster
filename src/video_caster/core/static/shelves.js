import { h } from "./dom.js";
import { episodeParts, inProgress, tileSub, wideSub } from "./util.js";
import { openShow, tapFile } from "./actions.js";

export function count(n) {
  return h("span", { class: "mga-sectionbar__aside" }, String(n).padStart(2, "0"));
}

export function blocks(progress) {
  const on = progress > 0 ? Math.max(1, Math.round(progress * 10)) : 0;
  return h("span", { class: "mga-blocks", "aria-hidden": "true" },
    Array.from({ length: 10 }, (_, i) => h("i", { class: i < on ? "on" : "" })));
}

export function art(url, title, shape, overlay = null) {
  const cls = `art art--${shape}`;
  const label = overlay === null ? null : h("span", { class: "art__overlay" }, overlay);
  if (url === null) return h("div", { class: `${cls} art--empty mga-halftone` }, h("b", {}, title), label);
  return h("div", { class: cls }, h("img", { src: url, alt: "", loading: "lazy" }), label);
}

function episodeOverlay(row) {
  const parts = episodeParts(row.subtitle);
  if (parts === null) return null;
  return [h("span", { class: "art__code" }, parts.code), parts.name === null ? null : ` ${parts.name}`];
}

function wideTile(row, live) {
  const sub = wideSub(row);
  return h("button", { class: "tile tile--wide", type: "button", disabled: !live, onclick: () => tapFile(row) },
    art(row.wide, row.title, "wide", episodeOverlay(row)),
    inProgress(row) ? blocks(row.position / row.duration) : null,
    h("span", { class: "tile__title" }, row.title),
    sub === null ? null : h("span", { class: "tile__sub" }, sub));
}

function posterTile(item, sub, onclick, live) {
  return h("button", { class: "tile tile--poster", type: "button", disabled: !live, onclick },
    art(item.poster, item.title, "poster"),
    h("span", { class: "tile__title" }, item.title),
    sub === null ? null : h("span", { class: "tile__sub" }, sub));
}

function episodeCount(n) {
  return n === 1 ? "1 episode" : `${n} episodes`;
}

function shelf(title, tiles) {
  if (tiles.length === 0) return null;
  return h("section", { class: "shelf" },
    h("h2", { class: "mga-sectionbar" }, title, count(tiles.length)),
    h("div", { class: "rail" }, tiles));
}

export function renderShelves(library, live) {
  return h("div", { class: "shelves" },
    shelf("Continue Watching", library.continue.map((row) => wideTile(row, live))),
    shelf("Shows", library.shows.map((show) =>
      posterTile(show, episodeCount(show.episode_count), () => openShow(show.key), live))),
    shelf("Movies", library.movies.map((row) => posterTile(row, tileSub(row), () => tapFile(row), live))),
    shelf("Newly Added", library.newly_added.map((row) => wideTile(row, live))),
  );
}
