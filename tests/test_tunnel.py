"""Drive real connections through the tunnel, with the helper as a local process."""

import asyncio
import shutil
import socket
import subprocess
import sys
import unittest

from hello_127 import args, host, launch, wire

PYTHON_FLOOR = shutil.which("python3.10")


def free_port():
    """Return a TCP port on 127.0.0.1 that nothing is listening on right now."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def to_port(port):
    """Return a forward that dials 127.0.0.1:port. `host.run` reads only the target."""
    return args.Forward("127.0.0.1", 0, "127.0.0.1", port)


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

    async def start(self, python=sys.executable, target=None):
        """Start an echo server and the tunnel. Return the helper's listening port."""
        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        target = target or server.sockets[0].getsockname()[1]
        inside = free_port()
        self.stop = asyncio.Event()
        command = [python, "-c", launch.source(wire, "listen", [("127.0.0.1", inside)])]
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


async def shout(reader, writer):
    """Read until the client's half-close, send it back in capitals, then close."""
    writer.write((await reader.read()).upper())
    await writer.drain()
    writer.close()


class RoutingTest(unittest.IsolatedAsyncioTestCase):
    """Two listeners through one helper, each relaying to its own server."""

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
        command = [python, "-c", launch.source(wire, "listen", listeners)]
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


class CollisionTest(unittest.TestCase):
    """A helper whose port is taken."""

    def test_port_in_use_is_one_line(self):
        """The helper says the port is taken and exits 1, with no traceback."""
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            port = taken.getsockname()[1]
            helper = subprocess.run(
                [sys.executable, "-c", launch.source(wire, "listen", [("127.0.0.1", port)])],
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
                [sys.executable, "-c", launch.source(wire, "listen", listeners)],
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
