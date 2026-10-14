import { h } from "./dom.js";
import { formatTime } from "./util.js";
import { call, castFile, closeDevices, selectDevice, submitPin } from "./actions.js";
import { update } from "./store.js";

const DEVICE_TYPES = { chromecast: "Chromecast", appletv: "Apple TV", dlna: "DLNA" };

function deviceType(device) {
  return device.device_type in DEVICE_TYPES ? DEVICE_TYPES[device.device_type] : device.device_type;
}

function resumeSheet(row, live) {
  return [
    h("h2", {}, row.title),
    row.subtitle === null ? null : h("p", {}, row.subtitle),
    h("button", { class: "btn primary", type: "button", disabled: !live, onclick: () => castFile(row, true) },
      `Resume at ${formatTime(row.position)}`),
    h("button", { class: "btn", type: "button", disabled: !live, onclick: () => castFile(row, false) }, "Start over"),
  ];
}

function devicesSheet(server, live) {
  const { scan } = server;
  return [
    h("h2", {}, server.pending === null ? "Choose a TV" : `Choose a TV for ${server.pending.title}`),
    scan.warning === "" ? null : h("p", {}, scan.warning),
    server.devices.length === 0 && !scan.running ? h("p", {}, "No devices found.") : null,
    server.devices.map((d) => h("button", {
      class: "btn device", type: "button", disabled: !live, onclick: () => selectDevice(d.id),
    },
      h("span", {}, d.name),
      h("span", { class: "row-meta" }, d.id === server.selected_device ? `✓ ${deviceType(d)}` : deviceType(d)))),
    h("button", {
      class: "btn", type: "button", disabled: !live || scan.running, onclick: () => call("/api/devices/scan"),
    }, scan.running ? "Scanning…" : "Scan again"),
  ];
}

function pinSheet(sheet, live) {
  const input = h("input", {
    class: "pin-input", inputmode: "numeric", autocomplete: "one-time-code", maxlength: 8, "aria-label": "PIN",
  });
  const onsubmit = (e) => {
    e.preventDefault();
    submitPin(input.value.trim());
  };
  return [
    h("h2", {}, `Enter the PIN shown on ${sheet.device_name}`),
    h("form", { onsubmit }, input, h("button", { class: "btn primary", type: "submit", disabled: !live }, "Submit")),
  ];
}

export function renderSheet(layer, state) {
  if (state.sheet === null) {
    layer.hidden = true;
    layer.replaceChildren();
    return;
  }
  const live = state.conn === "live";
  const { kind } = state.sheet;
  let body;
  if (kind === "resume") body = resumeSheet(state.sheet.row, live);
  else if (kind === "devices") body = devicesSheet(state.server, live);
  else body = pinSheet(state.sheet, live);
  const dismiss = () => (kind === "devices" ? closeDevices() : update({ sheet: null }));
  layer.hidden = false;
  layer.replaceChildren(
    h("div", { class: "backdrop", onclick: dismiss }),
    h("div", { class: "sheet", role: "dialog", "aria-modal": "true" }, body),
  );
}
