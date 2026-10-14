import { h } from "./dom.js";
import { episodeParts, formatTime, throttle } from "./util.js";
import { call, playNext } from "./actions.js";
import { nowPlaying } from "./store.js";

function tile(glyph, caption, label, onclick) {
  return h("button", { class: "mga-tile", type: "button", "aria-label": label, onclick },
    h("span", { class: "mga-tile__glyph", "aria-hidden": "true" }, glyph), caption);
}

export function createRemote(root) {
  let scrubbing = false;
  let sliding = false;
  let next = null;

  const empty = h("p", { class: "empty mga-halftone" }, "Nothing playing. Pick something in Library.");
  const starting = h("p", { class: "empty mga-halftone" });
  const kind = h("span", { class: "mga-card__kind" });
  const number = h("span", { class: "mga-card__cost" });
  const title = h("h2", { class: "mga-card__title" });
  const band = h("div", { class: "mga-card__band" });
  const scrub = h("input", { type: "range", min: 0, max: 0, step: 1, value: 0, "aria-label": "Position" });
  const elapsed = h("span", {});
  const total = h("span", {});
  const back = tile("◀◀", "10", "Back 10 seconds", () => call("/api/playback/seek", { offset: -10 }));
  const toggleGlyph = h("span", { class: "mga-tile__glyph", "aria-hidden": "true" });
  const toggle = h("button", {
    class: "mga-tile is-big", type: "button", "aria-label": "Play or pause", onclick: () => call("/api/playback/toggle"),
  }, toggleGlyph);
  const fwd = tile("▶▶", "30", "Forward 30 seconds", () => call("/api/playback/seek", { offset: 30 }));
  const volume = h("input", { type: "range", min: 0, max: 1, step: 0.01, value: 1, "aria-label": "Volume" });
  const stop = tile("■", "Stop", "Stop", () => call("/api/playback/stop"));
  const nextCaption = h("span", { class: "next-caption" });
  const nextBtn = h("button", { class: "mga-tile next-tile", type: "button", onclick: () => playNext(next) },
    h("span", { class: "mga-tile__glyph", "aria-hidden": "true" }, "▶▶|"), nextCaption);
  const sendVolume = throttle((level) => call("/api/playback/volume", { level }), 200);

  scrub.addEventListener("input", () => {
    scrubbing = true;
    elapsed.textContent = formatTime(Number(scrub.value));
  });
  scrub.addEventListener("change", async () => {
    await call("/api/playback/seek", { position: Number(scrub.value) });
    scrubbing = false;
  });
  volume.addEventListener("input", () => {
    sliding = true;
    sendVolume(Number(volume.value));
  });
  volume.addEventListener("change", async () => {
    await call("/api/playback/volume", { level: Number(volume.value) });
    sliding = false;
  });

  const card = h("article", { class: "mga-card" },
    h("div", { class: "mga-card__strip" }, kind, number),
    h("div", { class: "mga-card__art mga-halftone" }, title),
    band,
    h("div", { class: "mga-card__face" },
      scrub,
      h("div", { class: "times" }, elapsed, total)));
  const panel = h("div", { class: "remote" },
    card,
    h("div", { class: "mga-tiles transport" }, back, toggle, fwd),
    h("div", { class: "volume" }, h("span", { class: "volume-label" }, "Vol"), volume),
    h("div", { class: "mga-tiles actions" }, stop, nextBtn),
  );
  root.replaceChildren(empty, starting, panel);

  return {
    patch(state) {
      const now = nowPlaying(state);
      empty.hidden = now.kind !== "idle";
      starting.hidden = now.kind !== "starting";
      panel.hidden = now.kind !== "playing";
      if (now.kind === "starting") starting.textContent = `Starting ${now.title}…`;
      if (now.kind !== "playing") return;
      const { current } = now;
      const { status } = state.server;
      const parts = episodeParts(current.subtitle);
      kind.textContent = parts === null ? "Feature" : "Episode";
      number.textContent = parts === null ? "" : parts.episode;
      title.textContent = current.title;
      band.hidden = parts === null;
      if (parts !== null) band.textContent = parts.name === null ? parts.code : `${parts.code} · ${parts.name}`;
      total.textContent = formatTime(status.duration);
      if (!scrubbing) {
        scrub.max = String(status.duration);
        scrub.value = String(status.current_time);
        elapsed.textContent = formatTime(status.current_time);
      }
      if (!sliding) volume.value = String(status.volume);
      const playing = status.state === "playing";
      toggleGlyph.textContent = playing ? "❚❚" : "▶";
      toggle.classList.toggle("is-active", playing);
      const live = state.conn === "live";
      for (const control of [scrub, back, toggle, fwd, volume, stop, nextBtn]) control.disabled = !live;
      next = current.next;
      nextBtn.hidden = next === null;
      if (next !== null) {
        const nextParts = episodeParts(next.subtitle);
        nextCaption.textContent = `Next ${nextParts === null ? next.title : nextParts.code}`;
      }
    },
  };
}
