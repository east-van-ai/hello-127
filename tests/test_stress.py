"""Hold a hundred connections open at once through each helper."""

import asyncio
import sys
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
    echo,
    free_port,
    helper_command,
    to_port,
)

AT_ONCE = 100
ROUNDS = 3


async def held_round(port, at_once, tag, one_by_one=False):
    """Open `at_once` connections, then send on each, half-close, and return the answers.

    The connections open in one burst, or one after another with `one_by_one`.
    """
    if one_by_one:
        pairs = [await connect(port) for _ in range(at_once)]
    else:
        pairs = await asyncio.gather(*(connect(port) for _ in range(at_once)))
    payloads = [f"{tag}:{n}".encode() * 50 for n in range(at_once)]
    for (_, writer), payload in zip(pairs, payloads):
        writer.write(payload)
        writer.write_eof()
    answers = await asyncio.gather(*(reader.read() for reader, _ in pairs))
    for _, writer in pairs:
        writer.close()
    return payloads, answers


class StressTest(unittest.IsolatedAsyncioTestCase):
    """A hundred connections at once, three times over, through one helper."""

    LANGUAGE = "python"
    ROUNDS = ROUNDS
    ONE_BY_ONE = False

    async def test_hundred_at_once(self):
        """Every connection gets its own bytes back, and the tunnel still stops cleanly."""
        server = await asyncio.start_server(echo, "127.0.0.1", 0, backlog=AT_ONCE)
        self.addAsyncCleanup(server.wait_closed)
        self.addCleanup(server.close)
        target = server.sockets[0].getsockname()[1]
        inside = free_port()
        stop = asyncio.Event()
        command = helper_command([("127.0.0.1", inside)], self.LANGUAGE, sys.executable)
        tunnel = asyncio.create_task(host.run(command, [to_port(target)], stop=stop))
        try:
            for tag in range(self.ROUNDS):
                payloads, answers = await asyncio.wait_for(
                    held_round(inside, AT_ONCE, tag, self.ONE_BY_ONE), 60
                )
                self.assertEqual(answers, payloads)
        finally:
            stop.set()
            ended = await asyncio.wait_for(tunnel, 10)
        self.assertEqual(ended, (0, True))


@unittest.skipUnless(NODE, "node not on PATH")
class JavaScriptStressTest(StressTest):
    """The same load, with the JavaScript helper inside."""

    LANGUAGE = "node"


@unittest.skipUnless(PHP, "php not on PATH")
class PhpStressTest(StressTest):
    """The same load, with the PHP helper inside."""

    LANGUAGE = "php"


@unittest.skipUnless(RUBY, RUBY_SKIP)
class RubyStressTest(StressTest):
    """The same load, with the Ruby helper inside."""

    LANGUAGE = "ruby"


@unittest.skipUnless(PERL, PERL_SKIP)
class PerlStressTest(StressTest):
    """The same load, with the Perl helper inside."""

    LANGUAGE = "perl"


@unittest.skipUnless(BUSYBOX, BUSYBOX_SKIP)
class BusyBoxStressTest(StressTest):
    """The same load, with the BusyBox helper inside.

    BusyBox `nc -lk` resets part of a burst of a dozen, so the connections open
    one after another. Each costs about seven processes, so one round.
    """

    LANGUAGE = "busybox"
    ROUNDS = 1
    ONE_BY_ONE = True
