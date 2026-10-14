import { backoffDelay } from "./util.js";

async function request(method, path, body) {
  const init = { method };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  let resp;
  try {
    resp = await fetch(path, init);
  } catch (e) {
    return { ok: false, status: 0, error: e.message, network: true };
  }
  let payload;
  try {
    payload = await resp.json();
  } catch {
    return { ok: false, status: resp.status, error: `Unexpected response (${resp.status})`, network: false };
  }
  if (!resp.ok) return { ok: false, status: resp.status, error: payload.error, network: false };
  return { ok: true, data: payload };
}

export const get = (path) => request("GET", path);
export const post = (path, body) => request("POST", path, body);

export function connect(onEvent, onConn) {
  const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/events`;
  let attempt = 0;
  let timer = null;
  let socket = null;

  function open() {
    clearTimeout(timer);
    timer = null;
    socket = new WebSocket(url);
    socket.onopen = () => {
      attempt = 0;
      onConn("live");
    };
    socket.onmessage = (message) => onEvent(JSON.parse(message.data));
    socket.onclose = () => {
      socket = null;
      onConn("retrying");
      timer = setTimeout(open, backoffDelay(attempt));
      attempt += 1;
    };
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    // iOS can leave a dead socket looking OPEN after sleep; a fresh one brings a fresh snapshot.
    if (socket !== null) {
      socket.onclose = null;
      socket.close();
    }
    attempt = 0;
    onConn("retrying");
    open();
  });

  onConn("connecting");
  open();
}
