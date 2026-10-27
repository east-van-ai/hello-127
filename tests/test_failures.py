"""Pin how the tunnel fails today, so a change in that behaviour shows up red."""

import asyncio
import socket
import struct
import unittest

from hello_127 import host
from tests.test_tunnel import (
    BUSYBOX,
    BUSYBOX_SKIP,
    NODE,
    PERL,
    PERL_SKIP,
    PHP,
    RUBY,
    RUBY_SKIP,
    connect,
    free_port,
    helper_command,
    round_trip,
    to_port,
)

FLOOD = 32 * 1024 * 1024
STALL_WAIT = 1.0


async def flood_or_echo(reader, writer):
    """Answer `flood` with more bytes than the buffers hold. Echo anything else."""
    request = await reader.read()
    if request == b"flood":
        writer.write(b"x" * FLOOD)
    else:
        writer.write(request)
    try:
        await writer.drain()
    except ConnectionError:
        pass
    writer.close()


async def half_then_reset(reader, writer):
    """Send part of a reply, then reset the connection instead of closing it."""
    await reader.read()
    writer.write(b"partial")
    await writer.drain()
    sock = writer.get_extra_info("socket")
    # Linger with a zero timeout turns the close into a reset.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    writer.transport.abort()


class FailureTest(unittest.IsolatedAsyncioTestCase):
    """The tunnel against servers that misbehave, with the helper as a local process."""

    LANGUAGE = "python"

    async def start(self, handler):
        """Start `handler` as the far side and the tunnel. Return the helper's port."""
        server = await asyncio.start_server(handler, "127.0.0.1", 0)
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        target = server.sockets[0].getsockname()[1]
        inside = free_port()
        self.stop = asyncio.Event()
        command = helper_command([("127.0.0.1", inside)], self.LANGUAGE)
        self.tunnel = asyncio.create_task(
            host.run(command, [to_port(target)], stop=self.stop)
        )
        return inside

    async def finish(self):
        """Stop the tunnel and return what `run` returned."""
        self.stop.set()
        return await asyncio.wait_for(self.tunnel, 10)

    async def test_slow_reader_stalls_the_others(self):
        """A client that stops reading freezes every connection until it reads again."""
        inside = await self.start(flood_or_echo)
        reader, writer = await connect(inside)
        writer.write(b"flood")
        writer.write_eof()
        await asyncio.sleep(STALL_WAIT)

        small = asyncio.create_task(round_trip(inside, b"small"))
        done, _ = await asyncio.wait({small}, timeout=STALL_WAIT)
        self.assertEqual(done, set(), "the small echo got through a stalled pipe")

        self.assertEqual(len(await reader.read()), FLOOD)
        writer.close()
        self.assertEqual(await asyncio.wait_for(small, 5), b"small")
        await self.finish()

    async def test_reset_arrives_as_a_clean_end(self):
        """A reset on the far side reaches the client as an ordinary end of stream."""
        inside = await self.start(half_then_reset)
        answer = await asyncio.wait_for(round_trip(inside, b"ask"), 5)
        self.assertEqual(answer, b"partial")
        await self.finish()


@unittest.skipUnless(NODE, "node not on PATH")
class JavaScriptFailureTest(FailureTest):
    """The same misbehaving servers, with the JavaScript helper inside."""

    LANGUAGE = "node"


@unittest.skipUnless(PHP, "php not on PATH")
class PhpFailureTest(FailureTest):
    """The same misbehaving servers, with the PHP helper inside."""

    LANGUAGE = "php"


@unittest.skipUnless(RUBY, RUBY_SKIP)
class RubyFailureTest(FailureTest):
    """The same misbehaving servers, with the Ruby helper inside."""

    LANGUAGE = "ruby"


@unittest.skipUnless(PERL, PERL_SKIP)
class PerlFailureTest(FailureTest):
    """The same misbehaving servers, with the Perl helper inside."""

    LANGUAGE = "perl"


@unittest.skipUnless(BUSYBOX, BUSYBOX_SKIP)
class BusyBoxFailureTest(FailureTest):
    """The same misbehaving servers, with the BusyBox helper inside."""

    LANGUAGE = "busybox"


if __name__ == "__main__":
    unittest.main()
