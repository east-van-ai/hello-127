"""Drive real connections through the tunnel, with the helper as a local process."""

import asyncio
import shutil
import socket
import subprocess
import sys
import unittest
from unittest import mock

from hello_127 import args, errors, host, launch, shared, wire

PYTHON_FLOOR = shutil.which("python3.10")
NODE = shutil.which("node")
PHP = shutil.which("php")


def at_floor(language_name):
    """Return the interpreter on PATH for `language_name` if it is at or past its floor.

    macOS ships Ruby 2.6 in /usr/bin, below the floor, so finding one is not enough.
    Return None for a missing or too-old interpreter.
    """
    language = launch.LANGUAGES[language_name]
    interpreter, *flags = language.interpreter
    found = shutil.which(interpreter)
    if found is None:
        return None
    answer = subprocess.run(
        [found, *flags, language.probe], capture_output=True, encoding="utf-8"
    )
    version = shared.version_of(answer.stdout)
    return found if version is not None and version >= language.floor else None


RUBY = at_floor("ruby")
RUBY_SKIP = "no ruby 3.3 or newer on PATH"
PERL = at_floor("perl")
PERL_SKIP = "no perl 5.34 or newer on PATH"
BUSYBOX = at_floor("busybox")
BUSYBOX_SKIP = "no busybox 1.36 or newer with the full nc on PATH"
HALF_CLOSE_WAIT = 3.0


def helper_command(listeners, language="python", python=sys.executable, targets=()):
    """Return the command that runs the inside half in `language` as a local process.

    `listeners` are the `--out` listeners, and `targets` the `--in` targets it dials.
    """
    program = launch.source(wire, "listen", listeners, list(targets), language=language)
    if language == "node":
        return [NODE, "-e", program]
    if language == "php":
        return [PHP, "-r", program]
    if language == "ruby":
        return [RUBY, "-e", program]
    if language == "perl":
        return [PERL, "-e", program]
    if language == "busybox":
        return [BUSYBOX, "sh", "-c", program]
    return [python, "-c", program]


def needs_half_close(test):
    """Mark an `--in` test the BusyBox helper fails, since it cannot half-close.

    The round trip would wait forever for an end that never comes, so it gets
    `HALF_CLOSE_WAIT` seconds, and the tunnel stops either way.
    """

    @unittest.expectedFailure
    async def bounded(self):
        """Run `test` with a deadline, then stop the tunnel."""
        try:
            await asyncio.wait_for(test(self), HALF_CLOSE_WAIT)
        finally:
            self.stop.set()
            await asyncio.wait_for(self.tunnel, 10)

    bounded.__doc__ = test.__doc__
    return bounded


def free_port():
    """Return a TCP port on 127.0.0.1 that nothing is listening on right now."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def to_port(port):
    """Return an `--out` that dials 127.0.0.1:port. `host.run` reads only the target."""
    return args.Forward("127.0.0.1", 0, "127.0.0.1", port)


def on_port(port):
    """Return an `--in` that listens on the Mac's 127.0.0.1:port.

    `host.run` reads only the listener. The helper gets the target as its own argument.
    """
    return args.Forward("127.0.0.1", port, "127.0.0.1", 0)


async def echo(reader, writer):
    """Read until the client's half-close, send it all back, then close."""
    writer.write(await reader.read())
    await writer.drain()
    writer.close()


async def connect(port):
    """Connect to the helper, retrying while it starts up."""
    for _ in range(100):
        try:
            return await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(0.05)
    raise AssertionError(f"helper never listened on {port}")


async def round_trip(port, payload):
    """Send a payload, half-close, and return everything that comes back."""
    reader, writer = await connect(port)
    writer.write(payload)
    writer.write_eof()
    answer = await reader.read()
    writer.close()
    return answer


class TunnelTest(unittest.IsolatedAsyncioTestCase):
    """The helper and the Mac side, joined by real pipes, relaying to a real server."""

    LANGUAGE = "python"

    async def start(self, python=sys.executable, target=None):
        """Start an echo server and the tunnel. Return the helper's listening port."""
        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        target = target or server.sockets[0].getsockname()[1]
        inside = free_port()
        self.stop = asyncio.Event()
        command = helper_command([("127.0.0.1", inside)], self.LANGUAGE, python)
        self.tunnel = asyncio.create_task(
            host.run(command, [to_port(target)], stop=self.stop)
        )
        return inside

    async def finish(self):
        """Stop the tunnel and return what `run` returned."""
        self.stop.set()
        return await asyncio.wait_for(self.tunnel, 10)

    async def test_echo(self):
        """Bytes go through, and a half-close still gets the answer back."""
        inside = await self.start()
        self.assertEqual(await round_trip(inside, b"hello"), b"hello")
        self.assertEqual(await self.finish(), (0, True))

    async def test_many_at_once(self):
        """Several large connections share the pipe without mixing their bytes."""
        inside = await self.start()
        payloads = [bytes([n]) * 300_000 for n in range(8)]
        answers = await asyncio.gather(*(round_trip(inside, p) for p in payloads))
        self.assertEqual(answers, payloads)
        await self.finish()

    async def test_failed_dial_ends_the_read(self):
        """With nothing on the far side, the client reads an end, not a hang."""
        inside = await self.start(target=free_port())
        answer = await asyncio.wait_for(round_trip(inside, b"anyone?"), 5)
        self.assertEqual(answer, b"")
        await self.finish()

    @unittest.skipUnless(PYTHON_FLOOR, "python3.10 not on PATH")
    async def test_helper_on_python_floor(self):
        """The helper runs on the oldest Python a container may have."""
        inside = await self.start(python=PYTHON_FLOOR)
        self.assertEqual(await round_trip(inside, b"floor"), b"floor")
        self.assertEqual(await self.finish(), (0, True))


@unittest.skipUnless(NODE, "node not on PATH")
class JavaScriptTunnelTest(TunnelTest):
    """The same tunnel, with the JavaScript helper inside."""

    LANGUAGE = "node"
    test_helper_on_python_floor = None


@unittest.skipUnless(PHP, "php not on PATH")
class PhpTunnelTest(TunnelTest):
    """The same tunnel, with the PHP helper inside."""

    LANGUAGE = "php"
    test_helper_on_python_floor = None


@unittest.skipUnless(RUBY, RUBY_SKIP)
class RubyTunnelTest(TunnelTest):
    """The same tunnel, with the Ruby helper inside."""

    LANGUAGE = "ruby"
    test_helper_on_python_floor = None


@unittest.skipUnless(PERL, PERL_SKIP)
class PerlTunnelTest(TunnelTest):
    """The same tunnel, with the Perl helper inside."""

    LANGUAGE = "perl"
    test_helper_on_python_floor = None


@unittest.skipUnless(BUSYBOX, BUSYBOX_SKIP)
class BusyBoxTunnelTest(TunnelTest):
    """The same tunnel, with the BusyBox helper inside."""

    LANGUAGE = "busybox"
    test_helper_on_python_floor = None


async def shout(reader, writer):
    """Read until the client's half-close, send it back in capitals, then close."""
    writer.write((await reader.read()).upper())
    await writer.drain()
    writer.close()


class RoutingTest(unittest.IsolatedAsyncioTestCase):
    """Two listeners through one helper, each relaying to its own server."""

    LANGUAGE = "python"

    async def route(self, python):
        """Send one connection through each listener, and return both answers."""
        targets = []
        for handler in (echo, shout):
            server = await asyncio.start_server(handler, "127.0.0.1", 0)
            self.addAsyncCleanup(server.wait_closed)
            self.addCleanup(server.close)
            targets.append(server.sockets[0].getsockname()[1])
        insides = [free_port(), free_port()]
        listeners = [("127.0.0.1", inside) for inside in insides]
        command = helper_command(listeners, self.LANGUAGE, python)
        stop = asyncio.Event()
        tunnel = asyncio.create_task(
            host.run(command, [to_port(target) for target in targets], stop=stop)
        )
        answers = await asyncio.gather(
            round_trip(insides[0], b"quiet"), round_trip(insides[1], b"loud")
        )
        stop.set()
        self.assertEqual(await asyncio.wait_for(tunnel, 10), (0, True))
        return answers

    async def test_each_listener_reaches_its_own_target(self):
        """The OPEN frame's index picks the target, so the answers do not cross."""
        self.assertEqual(await self.route(sys.executable), [b"quiet", b"LOUD"])

    @unittest.skipUnless(PYTHON_FLOOR, "python3.10 not on PATH")
    async def test_on_python_floor(self):
        """Two listeners work on the oldest Python a container may have."""
        self.assertEqual(await self.route(PYTHON_FLOOR), [b"quiet", b"LOUD"])


@unittest.skipUnless(NODE, "node not on PATH")
class JavaScriptRoutingTest(RoutingTest):
    """The same routing, with the JavaScript helper inside."""

    LANGUAGE = "node"
    test_on_python_floor = None


@unittest.skipUnless(PHP, "php not on PATH")
class PhpRoutingTest(RoutingTest):
    """The same routing, with the PHP helper inside."""

    LANGUAGE = "php"
    test_on_python_floor = None


@unittest.skipUnless(RUBY, RUBY_SKIP)
class RubyRoutingTest(RoutingTest):
    """The same routing, with the Ruby helper inside."""

    LANGUAGE = "ruby"
    test_on_python_floor = None


@unittest.skipUnless(PERL, PERL_SKIP)
class PerlRoutingTest(RoutingTest):
    """The same routing, with the Perl helper inside."""

    LANGUAGE = "perl"
    test_on_python_floor = None


@unittest.skipUnless(BUSYBOX, BUSYBOX_SKIP)
class BusyBoxRoutingTest(RoutingTest):
    """The same routing, with the BusyBox helper inside."""

    LANGUAGE = "busybox"
    test_on_python_floor = None


class CollisionTest(unittest.TestCase):
    """A helper whose port is taken."""

    LANGUAGE = "python"

    def test_port_in_use_is_one_line(self):
        """The helper says the port is taken and exits 1, with no traceback."""
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            port = taken.getsockname()[1]
            helper = subprocess.run(
                helper_command([("127.0.0.1", port)], self.LANGUAGE),
                input=b"",
                capture_output=True,
                timeout=10,
            )
        self.assertEqual(helper.returncode, 1)
        self.assertEqual(helper.stdout, b"")
        self.assertEqual(
            helper.stderr.decode(),
            f"hello-127: inside: cannot listen on 127.0.0.1:{port}: "
            "already in use in this container\n",
        )


    def test_second_listener_taken(self):
        """The first listener binds, the second cannot, and the helper exits 1."""
        free = free_port()
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            port = taken.getsockname()[1]
            listeners = [("127.0.0.1", free), ("127.0.0.1", port)]
            helper = subprocess.run(
                helper_command(listeners, self.LANGUAGE),
                input=b"",
                capture_output=True,
                timeout=10,
            )
        self.assertEqual(helper.returncode, 1)
        self.assertEqual(helper.stdout, b"")
        self.assertEqual(
            helper.stderr.decode(),
            f"hello-127: inside: listening on 127.0.0.1:{free}\n"
            f"hello-127: inside: cannot listen on 127.0.0.1:{port}: "
            "already in use in this container\n",
        )


@unittest.skipUnless(NODE, "node not on PATH")
class JavaScriptCollisionTest(CollisionTest):
    """The same taken ports, with the JavaScript helper."""

    LANGUAGE = "node"


@unittest.skipUnless(PHP, "php not on PATH")
class PhpCollisionTest(CollisionTest):
    """The same taken ports, with the PHP helper."""

    LANGUAGE = "php"


@unittest.skipUnless(RUBY, RUBY_SKIP)
class RubyCollisionTest(CollisionTest):
    """The same taken ports, with the Ruby helper."""

    LANGUAGE = "ruby"


@unittest.skipUnless(PERL, PERL_SKIP)
class PerlCollisionTest(CollisionTest):
    """The same taken ports, with the Perl helper."""

    LANGUAGE = "perl"


@unittest.skipUnless(BUSYBOX, BUSYBOX_SKIP)
class BusyBoxCollisionTest(CollisionTest):
    """The same taken ports, with the BusyBox helper."""

    LANGUAGE = "busybox"


class InTunnelTest(unittest.IsolatedAsyncioTestCase):
    """`--in`: the Mac listens, and the helper dials a real server on its loopback."""

    LANGUAGE = "python"

    async def serve(self, handler):
        """Start `handler` on a free port, and return the port."""
        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        return server.sockets[0].getsockname()[1]

    async def start(self, target, python=sys.executable, listeners=(), outs=()):
        """Start the tunnel with one `--in` to `target`. Return the Mac's port."""
        mac = free_port()
        self.stop = asyncio.Event()
        command = helper_command(list(listeners), self.LANGUAGE, python, [target])
        self.tunnel = asyncio.create_task(
            host.run(command, list(outs), [on_port(mac)], stop=self.stop)
        )
        return mac

    async def finish(self):
        """Stop the tunnel and return what `run` returned."""
        self.stop.set()
        return await asyncio.wait_for(self.tunnel, 10)

    async def test_echo(self):
        """Bytes go in and back, and a half-close still gets the answer."""
        mac = await self.start(("127.0.0.1", await self.serve(echo)))
        self.assertEqual(await round_trip(mac, b"hello"), b"hello")
        self.assertEqual(await self.finish(), (0, True))

    async def test_refused_dial_ends_the_read(self):
        """With nothing listening inside, the Mac's client reads an end, not a hang."""
        mac = await self.start(("127.0.0.1", free_port()))
        answer = await asyncio.wait_for(round_trip(mac, b"anyone?"), 5)
        self.assertEqual(answer, b"")
        self.assertEqual(await self.finish(), (0, True))

    async def test_both_directions_at_once(self):
        """Large connections each way share one helper without mixing their bytes.

        Both ends number their own connections, so a shared number would cross them.
        """
        inside = free_port()
        mac = await self.start(
            ("127.0.0.1", await self.serve(shout)),
            listeners=[("127.0.0.1", inside)],
            outs=[to_port(await self.serve(echo))],
        )
        payloads = [bytes([ord("a") + n]) * 200_000 for n in range(4)]
        outward = [round_trip(inside, payload) for payload in payloads]
        inward = [round_trip(mac, payload) for payload in payloads]
        answers = await asyncio.gather(*outward, *inward)
        self.assertEqual(answers, payloads + [payload.upper() for payload in payloads])
        self.assertEqual(await self.finish(), (0, True))

    @unittest.skipUnless(PYTHON_FLOOR, "python3.10 not on PATH")
    async def test_on_python_floor(self):
        """`--in` works on the oldest Python a container may have."""
        mac = await self.start(("127.0.0.1", await self.serve(echo)), python=PYTHON_FLOOR)
        self.assertEqual(await round_trip(mac, b"floor"), b"floor")
        self.assertEqual(await self.finish(), (0, True))


@unittest.skipUnless(NODE, "node not on PATH")
class JavaScriptInTunnelTest(InTunnelTest):
    """The same `--in`, with the JavaScript helper inside."""

    LANGUAGE = "node"
    test_on_python_floor = None


@unittest.skipUnless(PHP, "php not on PATH")
class PhpInTunnelTest(InTunnelTest):
    """The same `--in`, with the PHP helper inside."""

    LANGUAGE = "php"
    test_on_python_floor = None


@unittest.skipUnless(RUBY, RUBY_SKIP)
class RubyInTunnelTest(InTunnelTest):
    """The same `--in`, with the Ruby helper inside."""

    LANGUAGE = "ruby"
    test_on_python_floor = None


@unittest.skipUnless(PERL, PERL_SKIP)
class PerlInTunnelTest(InTunnelTest):
    """The same `--in`, with the Perl helper inside."""

    LANGUAGE = "perl"
    test_on_python_floor = None


@unittest.skipUnless(BUSYBOX, BUSYBOX_SKIP)
class BusyBoxInTunnelTest(InTunnelTest):
    """The same `--in`, with the BusyBox helper inside.

    The helper cannot pass the Mac client's half-close on to the server inside, so the
    round trips that end with one never get their answer.
    """

    LANGUAGE = "busybox"
    test_on_python_floor = None
    test_echo = needs_half_close(InTunnelTest.test_echo)
    test_both_directions_at_once = needs_half_close(InTunnelTest.test_both_directions_at_once)


class NumberingTest(unittest.IsolatedAsyncioTestCase):
    """The helper's own connection numbers, read off its stdout."""

    LANGUAGE = "python"

    async def test_helper_numbers_odd(self):
        """The helper's first two OPENs carry 1 and 3, leaving the even ones to the Mac."""
        inside = free_port()
        helper = await asyncio.create_subprocess_exec(
            *helper_command([("127.0.0.1", inside)], self.LANGUAGE),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )
        conns = []
        clients = []
        for _ in range(2):
            clients.append(await connect(inside))
            kind, conn, _ = await asyncio.wait_for(wire.read_frame(helper.stdout), 5)
            self.assertEqual(kind, wire.OPEN)
            conns.append(conn)
        for _, writer in clients:
            writer.close()
        helper.stdin.close()
        await asyncio.wait_for(helper.wait(), 10)
        self.assertEqual(conns, [1, 3])


@unittest.skipUnless(NODE, "node not on PATH")
class JavaScriptNumberingTest(NumberingTest):
    """The same numbers, from the JavaScript helper."""

    LANGUAGE = "node"


@unittest.skipUnless(PHP, "php not on PATH")
class PhpNumberingTest(NumberingTest):
    """The same numbers, from the PHP helper."""

    LANGUAGE = "php"


@unittest.skipUnless(RUBY, RUBY_SKIP)
class RubyNumberingTest(NumberingTest):
    """The same numbers, from the Ruby helper."""

    LANGUAGE = "ruby"


@unittest.skipUnless(PERL, PERL_SKIP)
class PerlNumberingTest(NumberingTest):
    """The same numbers, from the Perl helper."""

    LANGUAGE = "perl"


@unittest.skipUnless(BUSYBOX, BUSYBOX_SKIP)
class BusyBoxNumberingTest(NumberingTest):
    """The same numbers, from the BusyBox helper."""

    LANGUAGE = "busybox"


class MacListenerTest(unittest.IsolatedAsyncioTestCase):
    """An `--in` whose port is already taken on the Mac."""

    async def test_taken_port_is_a_readiness_error(self):
        """The bind fails with one line naming the Mac, and the helper never starts."""
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            port = taken.getsockname()[1]
            with mock.patch("asyncio.create_subprocess_exec") as spawn:
                with self.assertRaises(errors.ReadinessError) as caught:
                    await host.run(["true"], [], [on_port(port)])
        spawn.assert_not_called()
        self.assertEqual(
            str(caught.exception),
            f"cannot listen on 127.0.0.1:{port} on the Mac: already in use",
        )


class FrameTest(unittest.IsolatedAsyncioTestCase):
    """The frame format on its own."""

    async def test_round_trip(self):
        """A frame read back gives its kind, connection, and payload."""
        pipe = asyncio.StreamReader()
        pipe.feed_data(wire.frame(wire.DATA, 7, b"abc") + wire.frame(wire.CLOSE, 7))
        pipe.feed_eof()
        self.assertEqual(await wire.read_frame(pipe), (wire.DATA, 7, b"abc"))
        self.assertEqual(await wire.read_frame(pipe), (wire.CLOSE, 7, b""))
        self.assertIsNone(await wire.read_frame(pipe))

    async def test_open_carries_its_listener(self):
        """An OPEN frame's payload is its listener's index, in two bytes."""
        pipe = asyncio.StreamReader()
        pipe.feed_data(wire.frame(wire.OPEN, 3, wire.INDEX.pack(513)))
        pipe.feed_eof()
        kind, conn, payload = await wire.read_frame(pipe)
        self.assertEqual((kind, conn, wire.INDEX.unpack(payload)), (wire.OPEN, 3, (513,)))


if __name__ == "__main__":
    unittest.main()
