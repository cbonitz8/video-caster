import { test } from "node:test";
import assert from "node:assert/strict";
import { closeShow, openShow, refreshLibrary } from "../../src/video_caster/core/static/actions.js";
import { getState, update } from "../../src/video_caster/core/static/store.js";

const emptyLibrary = { continue: [], shows: [], movies: [], newly_added: [] };
const episode = {
  path: "/w/Show/e3.mkv", name: "e3.mkv", is_dir: false, size: 1, title: "Show", subtitle: "S01E03", position: 1200,
};

function serve(t, browseEntries) {
  const urls = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    urls.push(url);
    const data = url === "/api/library" ? emptyLibrary : browseEntries;
    return { ok: true, status: 200, json: async () => data };
  });
  return urls;
}

test("refreshing the library also reloads the open browse folder in place", async (t) => {
  const urls = serve(t, [episode]);
  const stack = [{ path: null, name: "Folders" }, { path: "/w/Show", name: "Show" }];
  update({ browse: { stack, entries: [{ ...episode, position: null }], error: null } });
  await refreshLibrary();
  assert.deepEqual(urls, ["/api/library", "/api/browse?path=%2Fw%2FShow"]);
  assert.deepEqual(getState().browse, { stack, entries: [episode], error: null });
});

test("refreshing the library home fetches only the library", async (t) => {
  const urls = serve(t, []);
  update({ browse: null });
  await refreshLibrary();
  assert.deepEqual(urls, ["/api/library"]);
  assert.deepEqual(getState().library, emptyLibrary);
});

test("openShow and closeShow set state.show", () => {
  openShow("ted lasso");
  assert.equal(getState().show, "ted lasso");
  closeShow();
  assert.equal(getState().show, null);
});
