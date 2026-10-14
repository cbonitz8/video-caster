export function initialState() {
  return {
    conn: "connecting",
    server: null,
    library: null,
    libraryStale: false,
    browse: null,
    tab: "library",
    sheet: null,
    starting: null,
    toast: null,
  };
}

function arrived(starting, current) {
  return starting !== null && current !== null && current.path === starting.path;
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
    const starting = arrived(state.starting, data.current) ? null : state.starting;
    return { ...state, server: data, libraryStale: true, sheet, starting };
  }
  if (type === "library_changed") return { ...state, libraryStale: true };
  if (type === "error") {
    const starting = data.source === "cast" ? null : state.starting;
    return { ...state, toast: { message: data.message }, starting };
  }
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
    case "current":
      return {
        ...state,
        server: { ...server, current: data.current, pending: data.pending },
        starting: arrived(state.starting, data.current) ? null : state.starting,
      };
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
