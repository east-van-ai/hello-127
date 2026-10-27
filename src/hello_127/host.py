"""The Mac side: the relay."""

import asyncio
import errno
import itertools
import signal
import socket

from hello_127 import errors, wire

STOP_GRACE = 5.0


def bind(ins):
    """Bind and listen on each `--in` listener on the Mac. Return the sockets.

    A listener that cannot bind is a readiness error, raised before the helper starts.
    """
    sockets = []
    for forward in ins:
        sock = socket.socket()
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((forward.bind, forward.port))
            sock.listen()
        except OSError as error:
            sock.close()
            for opened in sockets:
                opened.close()
            reason = error.strerror
            if error.errno == errno.EADDRINUSE:
                reason = "already in use"
            raise errors.ReadinessError(
                f"cannot listen on {forward.bind}:{forward.port} on the Mac: {reason}"
            ) from None
        sockets.append(sock)
    return sockets


async def run(command, outs, ins=(), stop=None):
    """Run the helper command, and relay connections both ways through it.

    The helper's OPEN names an `--out` by index in `outs`, and the connection goes to
    that forward's `host:hostport` on the Mac. Each `--in` in `ins` listens on the
    Mac, and its connections go to the helper, which dials the target inside.

    The helper runs in its own session, so Ctrl-C reaches only this process. Setting
    `stop` closes the helper's stdin, which tells it to exit. Return the helper's exit
    code and whether `stop` ended the run.
    """
    stop = stop or asyncio.Event()
    sockets = bind(ins)
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    tunnel = wire.Tunnel(process.stdout, process.stdin, {}, {})
    numbers = itertools.count(2, 2)
    servers = [
        await asyncio.start_server(wire.acceptor(tunnel, numbers, index), sock=sock)
        for index, sock in enumerate(sockets)
    ]
    targets = [(forward.host, forward.hostport) for forward in outs]

    relay = asyncio.create_task(wire.dispatch(tunnel, wire.dialer(targets)))
    stopped = asyncio.create_task(stop.wait())
    await asyncio.wait({relay, stopped}, return_when=asyncio.FIRST_COMPLETED)

    for server in servers:
        server.close()
    if stop.is_set():
        wire.log("outside: stopping, closing the helper's input")
        process.stdin.close()
    try:
        await asyncio.wait_for(process.wait(), STOP_GRACE)
    except TimeoutError:
        wire.log(f"outside: helper still running after {STOP_GRACE:g} s, killing exec")
        process.kill()
        await process.wait()
    await relay
    stopped.cancel()
    return process.returncode, stop.is_set()


async def run_until_signal(command, outs, ins):
    """Run the tunnel until SIGINT or SIGTERM, and return what `run` returns."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    for forward in outs:
        wire.log(
            f"outside: relaying inside {forward.bind}:{forward.port}"
            f" to {forward.host}:{forward.hostport}"
        )
    for forward in ins:
        wire.log(
            f"outside: listening on {forward.bind}:{forward.port}"
            f" for {forward.host}:{forward.hostport} inside"
        )
    wire.log("outside: Ctrl-C to stop")
    return await run(command, outs, ins, stop=stop)
