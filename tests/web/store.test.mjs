import { test } from "node:test";
import assert from "node:assert/strict";
import { initialState, nowPlaying, reduce } from "../../src/video_caster/core/static/store.js";

const snapshot = (overrides = {}) => ({
  status: { state: "idle", current_time: 0, duration: 0, volume: 1, title: "" },
  devices: [], selected_device: null, scan: { running: false, warning: "" },
  current: null, pending: null, casting: null, pin_request: null,
  ...overrides,
});
const ted = { path: "/tv/ted5.mkv", title: "Ted Lasso", subtitle: "S04E05", next: null };
const live = (overrides) => reduce(initialState(), { type: "state", data: snapshot(overrides) });
const starting = (path) => ({ path, title: "x", since: 0 });

test("state replaces server and marks the library stale", () => {
  const s = live();
  assert.deepEqual(s.server, snapshot());
  assert.equal(s.libraryStale, true);
});

test("state clears starting when the tapped file is already current", () => {
  const s = reduce({ ...initialState(), starting: starting(ted.path) },
    { type: "state", data: snapshot({ current: ted }) });
  assert.equal(s.starting, null);
});

test("state opens the PIN sheet when a pairing is waiting", () => {
  const s = live({ pin_request: { device_name: "Bedroom TV", protocol: "airplay" } });
  assert.deepEqual(s.sheet, { kind: "pin", device_name: "Bedroom TV" });
});

test("status replaces server.status", () => {
  const status = { state: "playing", current_time: 5, duration: 100, volume: 0.5, title: "" };
  assert.deepEqual(reduce(live(), { type: "status", data: status }).server.status, status);
});

test("devices merges into server", () => {
  const data = { devices: [{ id: "a", name: "TV" }], selected_device: "a", scan: { running: true, warning: "" } };
  const s = reduce(live(), { type: "devices", data });
  assert.deepEqual(s.server.devices, data.devices);
  assert.equal(s.server.selected_device, "a");
  assert.deepEqual(s.server.scan, data.scan);
});

test("current keeps starting while the server is casting or queueing that path", () => {
  const before = { ...live(), starting: starting(ted.path) };
  const casting = reduce(before, { type: "current", data: { current: null, pending: null, casting: ted } });
  assert.notEqual(casting.starting, null);
  const queued = reduce(before, { type: "current", data: { current: null, casting: null, pending: { ...ted, resume: false } } });
  assert.notEqual(queued.starting, null);
  const arrived = reduce(casting, { type: "current", data: { current: ted, pending: null, casting: null } });
  assert.equal(arrived.starting, null);
  assert.deepEqual(arrived.server.current, ted);
});

test("current clears starting once nothing on the server names that path", () => {
  const before = { ...live(), starting: starting(ted.path) };
  const other = { ...ted, path: "/tv/emily.mkv" };
  const s = reduce(before, { type: "current", data: { current: other, pending: null, casting: null } });
  assert.equal(s.starting, null);
});

test("a wake-up snapshot clears a starting whose cast died while asleep", () => {
  const before = { ...live(), starting: starting(ted.path) };
  assert.equal(reduce(before, { type: "state", data: snapshot() }).starting, null);
});

test("a playing status never clears starting", () => {
  const before = { ...live(), starting: starting(ted.path) };
  const status = { state: "playing", current_time: 1, duration: 100, volume: 1, title: "" };
  assert.notEqual(reduce(before, { type: "status", data: status }).starting, null);
});

test("pin_required opens and pin_resolved closes the PIN sheet only", () => {
  const opened = reduce(live(), { type: "pin_required", data: { device_name: "Bedroom TV", protocol: "airplay" } });
  assert.deepEqual(opened.sheet, { kind: "pin", device_name: "Bedroom TV" });
  const closed = reduce(opened, { type: "pin_resolved", data: { device_name: "Bedroom TV" } });
  assert.equal(closed.sheet, null);
  assert.equal(closed.server.pin_request, null);
  const devices = reduce({ ...live(), sheet: { kind: "devices" } }, { type: "pin_resolved", data: { device_name: "x" } });
  assert.deepEqual(devices.sheet, { kind: "devices" });
});

test("library_changed marks the library stale", () => {
  assert.equal(reduce({ ...live(), libraryStale: false }, { type: "library_changed", data: null }).libraryStale, true);
});

test("errors toast and leave starting to the server's casting state", () => {
  const before = { ...live(), starting: starting(ted.path) };
  const cast = reduce(before, { type: "error", data: { message: "Cast failed: x", source: "cast" } });
  assert.deepEqual(cast.toast, { message: "Cast failed: x" });
  assert.notEqual(cast.starting, null);
});

test("nowPlaying prefers the local starting, then the server's casting, then current", () => {
  assert.deepEqual(nowPlaying(initialState()), { kind: "idle" });
  assert.deepEqual(nowPlaying(live()), { kind: "idle" });
  const mine = { ...live({ current: ted }), starting: { path: "/tv/x.mkv", title: "X", since: 5 } };
  assert.deepEqual(nowPlaying(mine), { kind: "starting", title: "X", since: 5 });
  assert.deepEqual(nowPlaying(live({ casting: ted })), { kind: "starting", title: "Ted Lasso", since: null });
  assert.deepEqual(nowPlaying(live({ current: ted })), { kind: "playing", current: ted });
});

test("a server event before the snapshot is an error", () => {
  assert.throws(() => reduce(initialState(), { type: "status", data: {} }), /before the state snapshot/);
});

test("no show page is open initially", () => {
  assert.equal(initialState().show, null);
});
