import { test } from "node:test";
import assert from "node:assert/strict";
import { backoffDelay, formatLeft, formatTime, throttle } from "../../src/video_caster/core/static/util.js";

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
