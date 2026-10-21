import { test } from "node:test";
import assert from "node:assert/strict";
import { backoffDelay, episodeParts, formatLeft, formatTime, throttle, tileSub, seasonLine, episodeTitle, findShow, canResume, wideSub } from "../../src/video_caster/core/static/util.js";

test("backoff doubles from 1s and caps at 10s", () => {
  assert.deepEqual([0, 1, 2, 3, 4, 5].map(backoffDelay), [1000, 2000, 4000, 8000, 10000, 10000]);
});

test("formatTime", () => {
  assert.equal(formatTime(7), "0:07");
  assert.equal(formatTime(7.9), "0:07");
  assert.equal(formatTime(724), "12:04");
  assert.equal(formatTime(3753), "1:02:33");
});

test("formatLeft", () => {
  assert.equal(formatLeft(1000, 2080), "18m left");
  assert.equal(formatLeft(0, 5400), "1h 30m left");
  assert.equal(formatLeft(99, 100), "1m left");
});

test("throttle passes the first and last call of a burst", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"] });
  const calls = [];
  const throttled = throttle((v) => calls.push(v), 200);
  throttled(1);
  throttled(2);
  throttled(3);
  assert.deepEqual(calls, [1]);
  t.mock.timers.tick(200);
  assert.deepEqual(calls, [1, 3]);
});

test("episodeParts splits a subtitle into code, episode number and name", () => {
  assert.deepEqual(episodeParts("S04E05 · Riches of Embarrassment"),
    { code: "S04E05", episode: "05", name: "Riches of Embarrassment" });
  assert.deepEqual(episodeParts("S01E12"), { code: "S01E12", episode: "12", name: null });
  assert.equal(episodeParts(null), null);
});

test("tileSub: episode in progress", () => {
  assert.equal(tileSub({ subtitle: "S04E06 · Don't Jump", position: 1040, duration: 2862 }), "S04E06 · 30m left");
});

test("tileSub: named episode not in progress", () => {
  assert.equal(tileSub({ subtitle: "S01E02 · Into the Storm", position: null, duration: null }), "S01E02 · Into the Storm");
});

test("tileSub: unnamed episode not in progress", () => {
  assert.equal(tileSub({ subtitle: "S01E02", position: null, duration: null }), "S01E02");
});

test("tileSub: movie in progress", () => {
  assert.equal(tileSub({ subtitle: null, position: 60, duration: 7920 }), "2h 11m left");
});

test("tileSub: movie not in progress", () => {
  assert.equal(tileSub({ subtitle: null, position: null, duration: null }), null);
});

test("tileSub: duration 0 is not in progress", () => {
  assert.equal(tileSub({ subtitle: null, position: 50, duration: 0 }), null);
  assert.equal(tileSub({ subtitle: "S01E02", position: 50, duration: 0 }), "S01E02");
});

const season = (n, count) => ({ season: n, episodes: Array.from({ length: count }, () => ({})) });

test("seasonLine: one season", () => {
  assert.equal(seasonLine({ episode_count: 7, seasons: [season(4, 7)] }), "Season 4 · 7 eps");
});

test("seasonLine: one episode", () => {
  assert.equal(seasonLine({ episode_count: 1, seasons: [season(1, 1)] }), "Season 1 · 1 ep");
});

test("seasonLine: several seasons", () => {
  assert.equal(seasonLine({ episode_count: 18, seasons: [season(1, 10), season(2, 8)] }), "2 seasons · 18 eps");
});

test("seasonLine: specials only", () => {
  assert.equal(seasonLine({ episode_count: 3, seasons: [season(0, 3)] }), "Specials · 3 eps");
});

test("episodeTitle falls back to the episode number", () => {
  assert.equal(episodeTitle({ subtitle: "S01E03" }), "Episode 3");
  assert.equal(episodeTitle({ subtitle: "S04E07 · Yes & Baby" }), "Yes & Baby");
});

test("findShow returns the show or null for a vanished key", () => {
  const library = { shows: [{ key: "a" }] };
  assert.deepEqual(findShow(library, "a"), { key: "a" });
  assert.equal(findShow(library, "b"), null);
});

test("canResume: a saved position resumes even without a duration", () => {
  assert.equal(canResume({ position: 50, duration: 0 }), true);
  assert.equal(canResume({ position: 1040, duration: 2862 }), true);
  assert.equal(canResume({ position: null, duration: null }), false);
});

test("wideSub: time left only, since the episode name is on the image", () => {
  assert.equal(wideSub({ subtitle: "S04E06 · Don't Jump", position: 1040, duration: 2862 }), "30m left");
  assert.equal(wideSub({ subtitle: "S04E08 · Follow the Anger", position: null, duration: null }), null);
  assert.equal(wideSub({ subtitle: null, position: 60, duration: 7920 }), "2h 11m left");
  assert.equal(wideSub({ subtitle: null, position: 50, duration: 0 }), null);
});
