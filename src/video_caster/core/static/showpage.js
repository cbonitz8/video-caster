import { h } from "./dom.js";
import {
  canResume, episodeParts, episodeTitle, formatLeft, formatTime, inProgress, seasonLabel, seasonLine,
} from "./util.js";
import { castFile, closeShow, tapFile } from "./actions.js";
import { art, blocks, count } from "./shelves.js";

function upNext(row, live) {
  const resume = canResume(row);
  return h("div", { class: "mga-dialogue show-next" },
    h("span", { class: "mga-dialogue__tab" }, "UP NEXT"),
    h("div", { class: "mga-dialogue__box" },
      h("p", { class: "mga-dialogue__line" }, row.subtitle === null ? row.title : row.subtitle),
      h("div", { class: "mga-dialogue__actions" },
        h("button", {
          class: "mga-dialogue__choice is-primary", type: "button", disabled: !live,
          onclick: () => castFile(row, resume),
        },
        h("span", { class: "choice-label" }, resume ? "Resume" : "Play"),
        resume ? h("span", { class: "choice-meta" }, formatTime(row.position)) : null))));
}

function episodeRow(row, live) {
  const parts = episodeParts(row.subtitle);
  let meta = "";
  if (row.watched) meta = "■ Seen";
  else if (inProgress(row)) meta = formatLeft(row.position, row.duration);
  return h("button", { class: "mga-row", type: "button", disabled: !live, onclick: () => tapFile(row) },
    h("span", { class: "mga-row__text" },
      h("span", { class: "mga-row__title" }, episodeTitle(row)),
      parts === null ? null : h("span", { class: "mga-row__sub" }, h("span", { class: "mga-row__code" }, parts.code)),
      inProgress(row) ? blocks(row.position / row.duration) : null),
    h("span", { class: "mga-row__meta" }, meta));
}

export function renderShow(show, live) {
  return h("div", { class: "show" },
    h("div", { class: "browse-bar" },
      h("button", { class: "browse-back", type: "button", "aria-label": "Back", onclick: closeShow }, "◀"),
      h("h2", { class: "mga-sectionbar browse-title" }, "Shows")),
    h("div", { class: "show-hero" },
      art(show.poster, show.title, "poster"),
      h("div", { class: "show-hero__text" },
        h("h2", { class: "show-hero__title" }, show.title),
        h("span", { class: "show-hero__meta" }, seasonLine(show)))),
    show.up_next === null ? null : upNext(show.up_next, live),
    show.seasons.map((season) => h("section", { class: "lib-section" },
      h("h2", { class: "mga-sectionbar" }, seasonLabel(season.season), count(season.episodes.length)),
      h("div", { class: "mga-list" }, season.episodes.map((row) => episodeRow(row, live))))));
}
