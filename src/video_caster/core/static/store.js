export function initialState() {
  return {
    conn: "connecting",
    server: null,
    library: null,
    libraryStale: false,
    browse: null,
    show: null,
    tab: "library",
    sheet: null,
    starting: null,
    toast: null,
  };
}

const names = (entry, path) => entry !== null && entry.path === path;

function settle(starting, server) {
  if (starting === null || names(server.current, starting.path)) return null;
  return names(server.casting, starting.path) || names(server.pending, starting.path) ? starting : null;
}

function closePin(sheet) {
  return sheet !== null && sheet.kind === "pin" ? null : sheet;
}

export function reduce(state, event) {
  const { type, data } = event;
  if (type === "state") {
    const sheet = data.pin_request !== null
      ? { kind: "pin", device_name: data.pin_request.device_name }
      : closePin(state.sheet);
    return { ...state, server: data, libraryStale: true, sheet, starting: settle(state.starting, data) };
  }
  if (type === "library_changed") return { ...state, libraryStale: true };
  if (type === "error") return { ...state, toast: { message: data.message } };
  if (state.server === null) throw new Error(`"${type}" event arrived before the state snapshot`);
  const server = state.server;
  switch (type) {
    case "status":
      return { ...state, server: { ...server, status: data } };
    case "devices":
      return {
        ...state,
        server: { ...server, devices: data.devices, selected_device: data.selected_device, scan: data.scan },
      };
    case "current": {
      const next = { ...server, current: data.current, pending: data.pending, casting: data.casting };
      return { ...state, server: next, starting: settle(state.starting, next) };
    }
    case "pin_required":
      return {
        ...state,
        server: { ...server, pin_request: data },
        sheet: { kind: "pin", device_name: data.device_name },
      };
    case "pin_resolved":
      return { ...state, server: { ...server, pin_request: null }, sheet: closePin(state.sheet) };
    default:
      return state;
  }
}

export function nowPlaying(state) {
  if (state.starting !== null) return { kind: "starting", title: state.starting.title, since: state.starting.since };
  const { server } = state;
  if (server === null) return { kind: "idle" };
  if (server.casting !== null) return { kind: "starting", title: server.casting.title, since: null };
  if (server.current !== null) return { kind: "playing", current: server.current };
  return { kind: "idle" };
}

let state = initialState();
const subscribers = new Set();

function notify() {
  for (const fn of subscribers) fn(state);
}

export function getState() {
  return state;
}

export function dispatch(event) {
  state = reduce(state, event);
  notify();
}

export function update(patch) {
  state = { ...state, ...patch };
  notify();
}

export function subscribe(fn) {
  subscribers.add(fn);
}
