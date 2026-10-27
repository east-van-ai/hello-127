// Carry TCP connections as frames over a pair of pipes: the inside half, in JavaScript.
//
// The twin of wire.py's inside half, for a container with node and no python3. The
// container receives this source through `node -e`, then one call to `listen`. It uses
// Node built-ins only, runs on Node 20, and never writes to stdout, which is the wire.
// The frame format is wire.py's: a change to one lands in the other.

"use strict";

const net = require("net");

const OPEN = 1;
const DATA = 2;
const CLOSE = 3;
const HEADER_SIZE = 9;
const EMPTY = Buffer.alloc(0);

// Print one line to stderr, since stdout belongs to the frames.
function log(message) {
  process.stderr.write(`hello-127: ${message}\n`);
}

// Return one frame: kind, connection number, payload length, then the payload.
function frame(kind, conn, payload = EMPTY) {
  const header = Buffer.alloc(HEADER_SIZE);
  header.writeUInt8(kind, 0);
  header.writeUInt32BE(conn, 1);
  header.writeUInt32BE(payload.length, 5);
  return Buffer.concat([header, payload]);
}

// Return the first whole frame in `pending` as [kind, conn, payload, rest], or null.
function nextFrame(pending) {
  if (pending.length < HEADER_SIZE) return null;
  const length = pending.readUInt32BE(5);
  if (pending.length < HEADER_SIZE + length) return null;
  return [
    pending.readUInt8(0),
    pending.readUInt32BE(1),
    pending.subarray(HEADER_SIZE, HEADER_SIZE + length),
    pending.subarray(HEADER_SIZE + length),
  ];
}

// Bind one listener, resolving to its server, or rejecting with the bind error.
function bind(address, port, accept) {
  return new Promise((resolve, reject) => {
    const server = net.createServer({ allowHalfOpen: true }, accept);
    server.once("error", reject);
    server.listen(port, address, () => {
      server.removeListener("error", reject);
      resolve(server);
    });
  });
}

// Listen on each [address, port] in `listeners`, and dial `targets` on request.
//
// The helper's OPEN carries its listener's index in `listeners`, so the Mac side
// knows where to dial. The Mac's OPEN carries an index in `targets`, the address and
// port to dial in here. A listener that cannot bind ends the helper, with no partial
// tunnel.
async function serveInside(listeners, targets) {
  const out = process.stdout;
  const links = new Map(); // conn -> { socket, remaining }
  const paused = new Set(); // sockets waiting for stdout to drain
  let nextConn = 1; // odd inside, even on the Mac

  // Count one direction of a connection as done, and drop it once both are.
  function finishHalf(conn) {
    const link = links.get(conn);
    if (link === undefined) return;
    link.remaining -= 1;
    if (link.remaining === 0) {
      links.delete(conn);
      link.socket.end();
    }
  }

  // Write a frame to stdout, and pause `socket` until stdout drains if it is full.
  function send(bytes, socket) {
    if (out.destroyed || out.writableEnded) return;
    if (!out.write(bytes) && socket !== undefined) {
      socket.pause();
      paused.add(socket);
    }
  }

  out.on("drain", () => {
    for (const socket of paused) socket.resume();
    paused.clear();
  });
  out.on("error", () => {}); // the Mac side went away; stdin ends next

  // Return the accept callback for the listener at `index`.
  function acceptor(index) {
    return (socket) => {
      const conn = nextConn;
      nextConn += 2;
      const announce = Buffer.alloc(2);
      announce.writeUInt16BE(index, 0);
      send(frame(OPEN, conn, announce));
      attach(conn, socket);
    };
  }

  // Record a connected socket under `conn`, and pump its reads into DATA frames.
  function attach(conn, socket) {
    links.set(conn, { socket, remaining: 2 });
    let reading = true;
    // Send CLOSE once this socket's reading ends, however it ends.
    const readEnded = () => {
      if (!reading) return;
      reading = false;
      paused.delete(socket);
      send(frame(CLOSE, conn));
      finishHalf(conn);
    };
    socket.on("data", (chunk) => send(frame(DATA, conn, chunk), socket));
    socket.on("end", readEnded);
    socket.on("error", () => {}); // a reset ends the read like an end; close follows
    socket.on("close", readEnded);
  }

  const servers = [];
  for (const [index, [address, port]] of listeners.entries()) {
    try {
      servers.push(await bind(address, port, acceptor(index)));
    } catch (error) {
      const reason =
        error.code === "EADDRINUSE" ? "already in use in this container" : error.code;
      log(`inside: cannot listen on ${address}:${port}: ${reason}`);
      for (const server of servers) server.close();
      process.exitCode = 1;
      return;
    }
    log(`inside: listening on ${address}:${port}`);
  }

  const input = process.stdin;
  let pending = EMPTY;
  let blocked = false;

  // Act on every whole frame in `pending`, stopping while a socket is full.
  function dispatch() {
    while (!blocked) {
      const got = nextFrame(pending);
      if (got === null) break;
      const [kind, conn, payload, rest] = got;
      pending = rest;
      if (kind === OPEN) {
        dial(conn, payload);
        continue;
      }
      const link = links.get(conn);
      if (link === undefined) continue;
      if (kind === DATA) {
        deliver(link.socket, payload);
      } else if (kind === CLOSE) {
        if (!link.socket.destroyed) link.socket.end();
        finishHalf(conn);
      }
    }
  }

  // Dial the target an OPEN frame names, and hold the pipe until the dial settles.
  //
  // No later frame is read before the dial lands, so no DATA overtakes its own
  // connection's dial. A dial that fails sends CLOSE, as the Mac side does.
  function dial(conn, payload) {
    const index = payload.readUInt16BE(0);
    const failed = (reason) => {
      log(`connection ${conn}: dial failed: ${reason}`);
      send(frame(CLOSE, conn));
    };
    if (index >= targets.length) {
      failed(`no target number ${index}`);
      return;
    }
    const [address, port] = targets[index];
    blocked = true;
    input.pause();
    const socket = net.connect({ host: address, port, allowHalfOpen: true });
    const settle = () => {
      blocked = false;
      input.resume();
      dispatch();
    };
    socket.once("connect", () => {
      socket.removeAllListeners("error");
      attach(conn, socket);
      settle();
    });
    socket.once("error", (error) => {
      failed(error.code);
      settle();
    });
  }

  // Write a DATA frame's payload to its socket, and hold the pipe while it is full.
  function deliver(socket, payload) {
    if (socket.destroyed || socket.writableEnded) return;
    if (socket.write(Buffer.from(payload))) return;
    blocked = true;
    input.pause();
    const unblock = () => {
      socket.removeListener("drain", unblock);
      socket.removeListener("close", unblock);
      blocked = false;
      input.resume();
      dispatch();
    };
    socket.on("drain", unblock);
    socket.on("close", unblock);
  }

  input.on("data", (chunk) => {
    pending = pending.length ? Buffer.concat([pending, chunk]) : chunk;
    dispatch();
  });
  input.on("end", () => {
    for (const { socket } of links.values()) socket.destroy();
    links.clear();
    for (const server of servers) server.close();
    log("inside: input ended, helper exiting");
  });
}

// Run the inside half until stdin ends. The container's entry point.
function listen(listeners, targets) {
  serveInside(listeners, targets);
}

module.exports = { OPEN, DATA, CLOSE, HEADER_SIZE, frame, nextFrame };
