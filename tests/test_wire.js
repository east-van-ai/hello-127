// Pin wire.js's frames and parser with fixed bytes, no timing involved.
// Run with `node --test tests/test_wire.js`; Node built-ins only.

"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const wire = require(path.join(__dirname, "..", "src", "hello_127", "wire.js"));

// Return a Buffer from a list of byte values.
function bytes(...values) {
  return Buffer.from(values);
}

test("frame writes kind, connection, and length big-endian, then the payload", () => {
  assert.deepEqual(
    wire.frame(wire.DATA, 258, Buffer.from("abc")),
    bytes(2, 0, 0, 1, 2, 0, 0, 0, 3, 0x61, 0x62, 0x63),
  );
});

test("frame with no payload is the header alone", () => {
  assert.deepEqual(wire.frame(wire.CLOSE, 7), bytes(3, 0, 0, 0, 7, 0, 0, 0, 0));
});

test("nextFrame waits for a whole header", () => {
  assert.equal(wire.nextFrame(Buffer.alloc(0)), null);
  assert.equal(wire.nextFrame(bytes(2, 0, 0, 0, 1, 0, 0, 0)), null);
});

test("nextFrame waits for a whole payload", () => {
  const whole = wire.frame(wire.DATA, 1, Buffer.from("hello"));
  assert.equal(wire.nextFrame(whole.subarray(0, whole.length - 1)), null);
});

test("nextFrame reads one frame exactly, with nothing left", () => {
  const [kind, conn, payload, rest] = wire.nextFrame(
    wire.frame(wire.DATA, 9, Buffer.from("hi")),
  );
  assert.deepEqual([kind, conn, payload.toString(), rest.length], [wire.DATA, 9, "hi", 0]);
});

test("nextFrame reads two frames in one buffer, one at a time", () => {
  const both = Buffer.concat([
    wire.frame(wire.DATA, 1, Buffer.from("one")),
    wire.frame(wire.CLOSE, 1),
  ]);
  const [kind, , payload, rest] = wire.nextFrame(both);
  assert.deepEqual([kind, payload.toString()], [wire.DATA, "one"]);
  const [kind2, conn2, payload2, rest2] = wire.nextFrame(rest);
  assert.deepEqual([kind2, conn2, payload2.length, rest2.length], [wire.CLOSE, 1, 0, 0]);
});

test("nextFrame reads a DATA frame with an empty payload", () => {
  const [kind, conn, payload] = wire.nextFrame(wire.frame(wire.DATA, 4, Buffer.alloc(0)));
  assert.deepEqual([kind, conn, payload.length], [wire.DATA, 4, 0]);
});

test("a header split at any offset reads once both parts arrive", () => {
  const whole = wire.frame(wire.DATA, 5, Buffer.from("split"));
  for (let at = 1; at < wire.HEADER_SIZE; at++) {
    const first = whole.subarray(0, at);
    assert.equal(wire.nextFrame(first), null, `split at ${at}`);
    const [, conn, payload] = wire.nextFrame(Buffer.concat([first, whole.subarray(at)]));
    assert.deepEqual([conn, payload.toString()], [5, "split"], `split at ${at}`);
  }
});

test("an OPEN carries its listener's index in two bytes", () => {
  const index = Buffer.alloc(2);
  index.writeUInt16BE(513, 0);
  const [kind, conn, payload] = wire.nextFrame(wire.frame(wire.OPEN, 3, index));
  assert.deepEqual([kind, conn, payload.readUInt16BE(0)], [wire.OPEN, 3, 513]);
});

test("the largest connection number survives the round trip", () => {
  const [, conn] = wire.nextFrame(wire.frame(wire.CLOSE, 2 ** 32 - 1));
  assert.equal(conn, 2 ** 32 - 1);
});
