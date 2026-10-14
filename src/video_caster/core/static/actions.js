import { get, post } from "./api.js";
import { getState, update } from "./store.js";

export function showError(result) {
  if (result.network) return; // the dropped socket drives the reconnect strip instead
  const message = result.status === 504 ? "TV didn't respond — try again" : result.error;
  update({ toast: { message } });
}

export async function call(path, body) {
  const result = await post(path, body);
  if (!result.ok) showError(result);
  return result;
}

export async function refreshLibrary() {
  update({ libraryStale: false });
  const result = await get("/api/library");
  if (result.ok) update({ library: result.data });
  else showError(result);
  const { browse } = getState();
  if (browse !== null && browse.entries !== null) await reloadBrowse(browse);
}

function browseUrl(stack) {
  const here = stack[stack.length - 1];
  return here.path === null ? "/api/browse" : `/api/browse?path=${encodeURIComponent(here.path)}`;
}

async function reloadBrowse(browse) {
  const result = await get(browseUrl(browse.stack));
  if (result.ok && getState().browse === browse) update({ browse: { ...browse, entries: result.data } });
}

export function tapFile(row) {
  if (row.position !== null) update({ sheet: { kind: "resume", row } });
  else castFile(row, false);
}

export async function castFile(row, resume) {
  update({ sheet: null, starting: { path: row.path, title: row.title, since: Date.now() } });
  const result = await call("/api/cast", { path: row.path, resume });
  if (!result.ok) update({ starting: null });
  else if (result.data.status === "waiting_for_device") update({ sheet: { kind: "devices" } });
}

export async function playNext(next) {
  update({ starting: { path: next.path, title: next.title, since: Date.now() } });
  const result = await call("/api/playback/next");
  if (!result.ok) update({ starting: null });
}

export async function selectDevice(id) {
  const result = await call("/api/devices/select", { device_id: id });
  if (result.ok) update({ sheet: null });
}

export async function closeDevices() {
  const { server } = getState();
  update({ sheet: null });
  if (server.pending !== null) {
    update({ starting: null });
    await call("/api/playback/stop");
  }
}

export async function submitPin(pin) {
  const result = await call("/api/pairing/pin", { pin });
  if (result.ok) update({ sheet: null });
}

async function loadBrowse(stack) {
  const browse = { stack, entries: null, error: null };
  update({ browse });
  const result = await get(browseUrl(stack));
  if (getState().browse !== browse) return; // navigated elsewhere while loading
  if (result.ok) {
    update({ browse: { stack, entries: result.data, error: null } });
  } else {
    showError(result);
    update({ browse: { stack, entries: null, error: result.error } });
  }
}

export function openBrowse(folder) {
  const { browse } = getState();
  return loadBrowse(browse === null ? [folder] : [...browse.stack, folder]);
}

export function browseBack() {
  const stack = getState().browse.stack.slice(0, -1);
  if (stack.length === 0) update({ browse: null });
  else loadBrowse(stack);
}
