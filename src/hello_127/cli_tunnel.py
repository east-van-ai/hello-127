"""
        hello-127 -- Tunnel

https://github.com/east-van-ai/hello-127

Starts a helper inside a running container and relays connections
between its loopback and the Mac's, in either direction. Give it at least
one --out or --in; there is no default. With
`--out 11434:127.0.0.1:11434`, the helper listens on 127.0.0.1:11434
inside, and the Mac dials Ollama on 127.0.0.1:11434, so a program in the
container reaches Ollama as if it were local, even with --network none.

--out listens inside and dials the Mac, in `ssh -R`'s shape: BIND:PORT is
where the helper listens inside, and HOST:HOSTPORT is what the Mac dials.
BIND may be left out, and is then 127.0.0.1. Every address must be
loopback, 127.0.0.1 to 127.255.255.255. The Mac answers only on the 127.x
addresses its lo0 carries, by default 127.0.0.1 alone. Another HOST leaves
each connection hanging until macOS gives up, after about 75 seconds.

--in listens on the Mac and dials inside, in `ssh -L`'s shape: BIND:PORT is
where the Mac listens, and HOST:HOSTPORT is what the helper dials inside.
It reaches a service in a container that `-p` cannot publish, such as one
started with --network none. The same loopback rule holds on both ends.

--out and --in may each repeat, once per listener, and one helper carries
them all. Two forwards may share a HOST:HOSTPORT, but two of the same flag
may not share a BIND:PORT. --in alone listens on nothing inside. A HOST
that hangs on the Mac stalls every forward, not just its own, until macOS
gives up.

RUNTIME `docker` runs the helper with `docker exec -i`, and `container` with
Apple Container's `container exec -i`. The container must already be running.

--languages lists the languages to try for the helper, in order, such as
`ruby,php`. Before the helper starts, the tunnel asks each interpreter in
turn for its version. The first one at or past its floor wins, and one line
on stderr names it. One that is missing or too old moves on to the next.
`python` needs python3, 3.10 or newer. `node` needs node, 20 or newer,
for an image such as `node:20-slim`. `perl` needs perl, 5.34 or newer, for
an image such as `debian:bookworm-slim`. `ruby` needs ruby, 3.3 or newer, for
an image such as `ruby:3.3-alpine`. `php` needs php, 8.2 or newer, for an image
such as `php:8.2-cli`. `busybox` needs busybox, 1.36 or newer, with the full
nc, for an image with no interpreter, such as `alpine`. Ubuntu's and Debian's
busybox packages cut nc down, so they count as no busybox. The BusyBox helper
cannot half-close: a client inside that ends its side early still gets its
answer, but an --in client that does the same waits forever. With none
left, the tunnel stops with one line saying what each language found. A
single name tries only that language. Whichever language it is, the Mac
side is the same.

The tunnel runs until Ctrl-C, which closes the helper's input so it exits.
If the helper lingers for 5 seconds, the exec is killed.
"""
import asyncio

from hello_127 import errors, host, launch, shared, wire

HELP = "relay loopback ports between a container and the Mac, either way"
USAGE = (
    "hello-127 tunnel RUNTIME CONTAINER (--out SPEC | --in SPEC)... [--languages LIST]"
)
SLOTS = ("RUNTIME", "CONTAINER")


def missing(parsed):
    """Return what the tunnel needs when it has no forward at all, or None."""
    return None if parsed.outs or parsed.ins else "at least one --out or --in"


def run(runtime, name, parsed):
    """Run the tunnel into container `name` until Ctrl-C."""
    language = shared.pick_language(runtime, name, parsed.languages, "tunnel")
    listeners = [(forward.bind, forward.port) for forward in parsed.outs]
    targets = [(forward.host, forward.hostport) for forward in parsed.ins]
    program = launch.source(wire, "listen", listeners, targets, language=language)
    command = launch.exec_command(
        runtime, name, program, language=language, interactive=True
    )
    try:
        code, stopped = asyncio.run(
            host.run_until_signal(command, parsed.outs, parsed.ins)
        )
    except FileNotFoundError:
        raise errors.ReadinessError(f"{command[0]} is not on PATH") from None
    if code and not stopped:
        raise errors.RuntimeFailure(f"the helper exited with code {code}")
