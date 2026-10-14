import { h } from "./dom.js";
import { formatTime } from "./util.js";
import { call, castFile, closeDevices, selectDevice, submitPin } from "./actions.js";
import { update } from "./store.js";

const DEVICE_TYPES = { chromecast: "Chromecast", appletv: "Apple TV", dlna: "DLNA" };

function deviceType(device) {
  return device.device_type in DEVICE_TYPES ? DEVICE_TYPES[device.device_type] : device.device_type;
}

function choice(label, { primary = false, disabled, onclick, meta = null }) {
  return h("button", {
    class: primary ? "mga-dialogue__choice is-primary" : "mga-dialogue__choice", type: "button", disabled, onclick,
  }, h("span", { class: "choice-label" }, label), meta === null ? null : h("span", { class: "choice-meta" }, meta));
}

function dialogue(speaker, lines, actions) {
  return h("div", { class: "mga-dialogue" },
    h("span", { class: "mga-dialogue__tab" }, speaker),
    h("div", { class: "mga-dialogue__box" },
      lines.map((line) => h("p", { class: "mga-dialogue__line" }, line)),
      h("div", { class: "mga-dialogue__actions" }, actions)));
}

function resumeSheet(row, live) {
  const speaker = row.subtitle === null ? row.title : `${row.title} · ${row.subtitle}`;
  return dialogue(speaker, [`You stopped at ${formatTime(row.position)}. Pick up where you left off?`], [
    choice(`Resume at ${formatTime(row.position)}`, { primary: true, disabled: !live, onclick: () => castFile(row, true) }),
    choice("Start over", { disabled: !live, onclick: () => castFile(row, false) }),
  ]);
}

function devicesSheet(server, live) {
  const { scan } = server;
  const lines = [server.pending === null ? "Choose a TV." : `Choose a TV for ${server.pending.title}.`];
  if (scan.warning !== "") lines.push(scan.warning);
  if (server.devices.length === 0 && !scan.running) lines.push("No devices found.");
  return dialogue("Devices", lines, [
    server.devices.map((d) => choice(d.name, {
      primary: d.id === server.selected_device,
      disabled: !live,
      onclick: () => selectDevice(d.id),
      meta: d.id === server.selected_device ? `✓ ${deviceType(d)}` : deviceType(d),
    })),
    choice(scan.running ? "Scanning…" : "Scan again", {
      disabled: !live || scan.running, onclick: () => call("/api/devices/scan"),
    }),
  ]);
}

function pinSheet(sheet, live) {
  const input = h("input", {
    class: "pin-input", inputmode: "numeric", autocomplete: "one-time-code", maxlength: 8, "aria-label": "PIN",
  });
  const onsubmit = (e) => {
    e.preventDefault();
    submitPin(input.value.trim());
  };
  return h("div", { class: "mga-dialogue" },
    h("span", { class: "mga-dialogue__tab" }, sheet.device_name),
    h("form", { class: "mga-dialogue__box", onsubmit },
      h("p", { class: "mga-dialogue__line" }, "Enter the PIN shown on the TV."),
      h("div", { class: "mga-dialogue__actions" },
        input,
        h("button", { class: "mga-dialogue__choice is-primary", type: "submit", disabled: !live },
          h("span", { class: "choice-label" }, "Submit")))));
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
