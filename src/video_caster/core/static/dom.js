export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else if (value === true) el.setAttribute(key, "");
    else if (value !== false && value !== null) el.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}
