"""Carry TCP connections as frames over a pair of pipes.

Both ends of the tunnel run this file. The Mac side imports it. The container side
receives its source through `python3 -c`, so it stays standard library only, runs on
Python 3.10, and never writes to stdout, which is the wire.
"""

import asyncio
import errno
import itertools
import struct
import sys
from collections import namedtuple

OPEN, DATA, CLOSE = 1, 2, 3
HEADER = struct.Struct("!BII")
INDEX = struct.Struct("!H")
CHUNK = 64 * 1024

Tunnel = namedtuple("Tunnel", "pipe_in pipe_out writers remaining")
"""One end of the tunnel: the pipe both ways, and its open connections.

`writers` maps a connection number to its socket's writer. `remaining` counts the
directions of that connection still open, from 2 down to 0.
"""


def log(message):
    """Print one line to stderr, since stdout belongs to the frames."""
    print(f"hello-127: {message}", file=sys.stderr, flush=True)


def frame(kind, conn, payload=b""):
    """Return one frame: kind, connection number, payload length, then the payload."""
    return HEADER.pack(kind, conn, len(payload)) + payload


async def read_frame(pipe):
    """Return the next (kind, conn, payload) from the pipe, or None at its end."""
    try:
        kind, conn, length = HEADER.unpack(await pipe.readexactly(HEADER.size))
        payload = await pipe.readexactly(length)
    except asyncio.IncompleteReadError:
        return None
    return kind, conn, payload


def open_link(tunnel, conn, writer):
    """Record a new connection with both of its directions open."""
    tunnel.writers[conn] = writer
    tunnel.remaining[conn] = 2


def finish_half(tunnel, conn):
    """Count one direction of a connection as done, and drop it once both are."""
    if conn not in tunnel.remaining:
        return
    tunnel.remaining[conn] -= 1
    if tunnel.remaining[conn] == 0:
        del tunnel.remaining[conn]
        tunnel.writers.pop(conn).close()


async def pump(tunnel, conn, reader):
    """Copy one socket's bytes into DATA frames, then send CLOSE at its end."""
    try:
        while True:
            chunk = await reader.read(CHUNK)
            if not chunk:
                break
            tunnel.pipe_out.write(frame(DATA, conn, chunk))
            await tunnel.pipe_out.drain()
    except ConnectionError:
        pass
    if not tunnel.pipe_out.is_closing():
        tunnel.pipe_out.write(frame(CLOSE, conn))
    finish_half(tunnel, conn)


async def deliver(tunnel, conn, payload):
    """Write a DATA frame's payload to its socket, if the socket is still there."""
    writer = tunnel.writers.get(conn)
    if writer is None or writer.is_closing():
        return
    writer.write(payload)
    try:
        await writer.drain()
    except ConnectionError:
        pass


def half_close(tunnel, conn):
    """Act on a CLOSE frame: end the socket's write side and count the direction."""
    writer = tunnel.writers.get(conn)
    if writer is None:
        return
    try:
        if writer.can_write_eof():
            writer.write_eof()
    except OSError:
        pass
    finish_half(tunnel, conn)


async def dispatch(tunnel, dial=None):
    """Act on frames from the pipe until it ends, then close every connection.

    `dial` takes an OPEN frame's payload and opens its far end. Only the Mac side
    passes one. It runs inline, so no DATA frame overtakes the dial for its own
    connection.
    """
    pumps = set()
    while True:
        got = await read_frame(tunnel.pipe_in)
        if got is None:
            break
        kind, conn, payload = got
        if kind == OPEN and dial is not None:
            try:
                reader, writer = await dial(payload)
            except OSError as error:
                log(f"connection {conn}: dial failed: {error}")
                tunnel.pipe_out.write(frame(CLOSE, conn))
                continue
            open_link(tunnel, conn, writer)
            task = asyncio.ensure_future(pump(tunnel, conn, reader))
            pumps.add(task)
            task.add_done_callback(pumps.discard)
        elif kind == DATA:
            await deliver(tunnel, conn, payload)
        elif kind == CLOSE:
            half_close(tunnel, conn)
    for writer in tunnel.writers.values():
        writer.close()
    tunnel.writers.clear()
    tunnel.remaining.clear()
    for task in pumps:
        task.cancel()


async def stdio_pipes():
    """Return this process's stdin and stdout as an asyncio reader and writer."""
    loop = asyncio.get_running_loop()
    pipe_in = asyncio.StreamReader()
    await loop.connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(pipe_in), sys.stdin.buffer
    )
    transport, protocol = await loop.connect_write_pipe(
        asyncio.streams.FlowControlMixin, sys.stdout.buffer
    )
    pipe_out = asyncio.StreamWriter(transport, protocol, None, loop)
    return pipe_in, pipe_out


async def serve_inside(listeners):
    """Listen on each (address, port) and send every connection through stdout.

    An OPEN frame carries its listener's index in `listeners`, so the Mac side knows
    where to dial. A listener that cannot bind ends the helper, with no partial tunnel.
    """
    pipe_in, pipe_out = await stdio_pipes()
    tunnel = Tunnel(pipe_in, pipe_out, {}, {})
    numbers = itertools.count(1)

    def acceptor(index):
        """Return the accept callback for the listener at `index`."""

        async def accept(reader, writer):
            """Number a new connection, announce it with its listener, and pump it."""
            conn = next(numbers)
            open_link(tunnel, conn, writer)
            pipe_out.write(frame(OPEN, conn, INDEX.pack(index)))
            await pump(tunnel, conn, reader)

        return accept

    servers = []
    for index, (address, port) in enumerate(listeners):
        try:
            servers.append(await asyncio.start_server(acceptor(index), address, port))
        except OSError as error:
            reason = error.strerror
            if error.errno == errno.EADDRINUSE:
                reason = "already in use in this container"
            log(f"inside: cannot listen on {address}:{port}: {reason}")
            raise SystemExit(1) from None
        log(f"inside: listening on {address}:{port}")
    await dispatch(tunnel)
    for server in servers:
        server.close()
    log("inside: input ended, helper exiting")


def listen(listeners):
    """Run the inside half until stdin ends. The container's entry point."""
    asyncio.run(serve_inside(listeners))
