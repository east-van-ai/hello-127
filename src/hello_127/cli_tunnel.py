"""
        hello-127 -- Tunnel

https://github.com/east-van-ai/hello-127

Starts a helper inside a running container and relays its connections to
a service on the Mac's loopback. By default the helper listens on
127.0.0.1:11434 inside, and the Mac dials Ollama on 127.0.0.1:11434, so a
program in the container reaches Ollama as if it were local, even with
--network none.

--forward changes both ends, in `ssh -L`'s shape: BIND:PORT is where the
helper listens inside, and HOST:HOSTPORT is what the Mac dials. BIND may be
left out, and is then 127.0.0.1. Every address must be loopback, 127.0.0.1
to 127.255.255.255. The Mac answers only on the 127.x addresses its lo0
carries, by default 127.0.0.1 alone. Another HOST leaves each connection
hanging until macOS gives up, after about 75 seconds.

--forward may repeat, once per listener, and one helper carries them all.
Two forwards may share a HOST:HOSTPORT, but not a BIND:PORT. A HOST that
hangs stalls every forward, not just its own, until macOS gives up.

RUNTIME `docker` runs the helper with `docker exec -i`, and `container` with
Apple Container's `container exec -i`. The container must already be running
and have python3, 3.10 or newer.

The tunnel runs until Ctrl-C, which closes the helper's input so it exits.
If the helper lingers for 5 seconds, the exec is killed.
"""
import asyncio

from hello_127 import errors, host, launch, wire

HELP = "relay a container's loopback port to the Mac's, 11434 by default"
USAGE = "hello-127 tunnel RUNTIME CONTAINER [--forward SPEC]..."
SLOTS = ("RUNTIME", "CONTAINER")


def run(runtime, name, parsed):
    """Run the tunnel into container `name` until Ctrl-C."""
    listeners = [(forward.bind, forward.port) for forward in parsed.forwards]
    program = launch.source(wire, "listen", listeners)
    command = launch.exec_command(runtime, name, program, interactive=True)
    try:
        code, stopped = asyncio.run(host.run_until_signal(command, parsed.forwards))
    except FileNotFoundError:
        raise errors.ReadinessError(f"{command[0]} is not on PATH") from None
    if code and not stopped:
        raise errors.RuntimeFailure(f"the helper exited with code {code}")
