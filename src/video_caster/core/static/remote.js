import { h } from "./dom.js";
import { formatTime, throttle } from "./util.js";
import { call, playNext } from "./actions.js";
import { nowPlaying } from "./store.js";

export function createRemote(root) {
  let scrubbing = false;
  let sliding = false;
  let next = null;

  const empty = h("p", { class: "empty" }, "Nothing playing. Pick something in Library.");
  const starting = h("p", { class: "empty" });
  const title = h("h2", { class: "np-title" });
  const sub = h("p", { class: "np-sub" });
  const scrub = h("input", { type: "range", min: 0, max: 0, step: 1, value: 0, "aria-label": "Position" });
  const elapsed = h("span", {});
  const total = h("span", {});
  const back = h("button", {
    type: "button", "aria-label": "Back 10 seconds", onclick: () => call("/api/playback/seek", { offset: -10 }),
  }, "↺10");
  const toggle = h("button", {
    class: "big", type: "button", "aria-label": "Play or pause", onclick: () => call("/api/playback/toggle"),
  });
  const fwd = h("button", {
    type: "button", "aria-label": "Forward 30 seconds", onclick: () => call("/api/playback/seek", { offset: 30 }),
  }, "30↻");
  const volume = h("input", { type: "range", min: 0, max: 1, step: 0.01, value: 1, "aria-label": "Volume" });
  const stop = h("button", { class: "btn", type: "button", onclick: () => call("/api/playback/stop") }, "Stop");
  const nextBtn = h("button", { class: "btn", type: "button", onclick: () => playNext(next) });
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

  const panel = h("div", { class: "remote" },
    h("div", {}, title, sub),
    h("div", {}, scrub, h("div", { class: "times" }, elapsed, total)),
    h("div", { class: "transport" }, back, toggle, fwd),
    h("div", { class: "volume" }, h("span", { "aria-hidden": "true" }, "🔈"), volume, h("span", { "aria-hidden": "true" }, "🔊")),
    h("div", { class: "actions" }, stop, nextBtn),
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
      title.textContent = current.title;
      sub.textContent = current.subtitle === null ? "" : current.subtitle;
      total.textContent = formatTime(status.duration);
      if (!scrubbing) {
        scrub.max = String(status.duration);
        scrub.value = String(status.current_time);
        elapsed.textContent = formatTime(status.current_time);
      }
      if (!sliding) volume.value = String(status.volume);
      toggle.textContent = status.state === "playing" ? "⏸" : "▶";
      const live = state.conn === "live";
      for (const control of [scrub, back, toggle, fwd, volume, stop, nextBtn]) control.disabled = !live;
      next = current.next;
      nextBtn.hidden = next === null;
      if (next !== null) nextBtn.textContent = `Next: ${next.subtitle === null ? next.title : next.subtitle} ⏭`;
    },
  };
}
