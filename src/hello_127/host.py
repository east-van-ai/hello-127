"""The Mac side: the relay."""

import asyncio
import signal

from hello_127 import wire

STOP_GRACE = 5.0


async def run(command, forwards, stop=None):
    """Run the helper command and relay each connection to its forward's target.

    An OPEN frame names its forward by index in `forwards`, and the connection goes to
    that forward's `host:hostport`.

    The helper runs in its own session, so Ctrl-C reaches only this process. Setting
    `stop` closes the helper's stdin, which tells it to exit. Return the helper's exit
    code and whether `stop` ended the run.
    """
    stop = stop or asyncio.Event()
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    tunnel = wire.Tunnel(process.stdout, process.stdin, {}, {})

    async def dial(payload):
        """Open a connection to the target of the forward an OPEN frame names."""
        (index,) = wire.INDEX.unpack(payload)
        if index >= len(forwards):
            raise OSError(f"no forward number {index}")
        return await asyncio.open_connection(forwards[index].host, forwards[index].hostport)

    relay = asyncio.create_task(wire.dispatch(tunnel, dial=dial))
    stopped = asyncio.create_task(stop.wait())
    await asyncio.wait({relay, stopped}, return_when=asyncio.FIRST_COMPLETED)

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


async def run_until_signal(command, forwards):
    """Run the tunnel until SIGINT or SIGTERM, and return what `run` returns."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    for forward in forwards:
        wire.log(
            f"outside: relaying {forward.bind}:{forward.port}"
            f" to {forward.host}:{forward.hostport}"
        )
    wire.log("outside: Ctrl-C to stop")
    return await run(command, forwards, stop=stop)
