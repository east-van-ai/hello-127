"""Check wire.sh's frames and parser against wire.py's, through busybox sh."""

import subprocess
import unittest
from pathlib import Path

from hello_127 import launch, wire
from tests.test_tunnel import BUSYBOX, BUSYBOX_SKIP

WIRE_SH = Path(wire.__file__).with_suffix(".sh").read_text(encoding="utf-8")


def run_busybox(script, stdin=b""):
    """Run wire.sh's source, then `script`, and return the finished run."""
    return subprocess.run(
        [BUSYBOX, "sh", "-c", f"{WIRE_SH}\n{script}"],
        input=stdin,
        capture_output=True,
        timeout=60,
    )


def octal(payload):
    """Return `payload` as printf octal escapes, so a shell line can carry any byte."""
    return "".join(f"\\{byte:03o}" for byte in payload)


@unittest.skipUnless(BUSYBOX, BUSYBOX_SKIP)
class BusyBoxTest(unittest.TestCase):
    """wire.sh on its own, through busybox sh."""

    def test_frames_match_python(self):
        """Both files write the same bytes for every kind, payload, and edge number."""
        cases = [
            (kind, conn, payload)
            for kind in (wire.OPEN, wire.DATA, wire.CLOSE)
            for conn in (1, 2**32 - 1)
            for payload in (b"", b"\x00hello\xff")
        ]
        lines = ['D=$(mktemp -d)', ': > "$D/out"']
        for kind, conn, payload in cases:
            lines.append(f"printf '{octal(payload)}' > \"$D/p\"")
            lines.append(f'frame {kind} {conn} "$D/p"')
        lines.append('cat "$D/out"')
        lines.append('rm -rf "$D"')
        run = run_busybox("\n".join(lines))
        self.assertEqual(run.returncode, 0, run.stderr)
        expected = b"".join(wire.frame(kind, conn, payload) for kind, conn, payload in cases)
        self.assertEqual(run.stdout, expected)

    def test_parser_reads_whole_frames(self):
        """A DATA frame bigger than a pipe's buffer, then an OPEN, both read whole.

        The DATA frame names no connection, so the helper drops it. The OPEN asks for
        a target the helper does not have, so it answers CLOSE. A misread length would
        take the OPEN for payload, and nothing would come back.
        """
        stdin = wire.frame(wire.DATA, 7, bytes(range(256)) * 400) + wire.frame(
            wire.OPEN, 2, wire.INDEX.pack(0)
        )
        run = run_busybox("listen '' ''", stdin)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout, wire.frame(wire.CLOSE, 2))
        self.assertEqual(
            run.stderr.decode(),
            "hello-127: connection 2: dial failed: no target number 0\n"
            "hello-127: inside: input ended, helper exiting\n",
        )

    def test_literal_round_trips(self):
        """Arguments with quotes, a backslash, `$x`, and spaces reach sh unchanged."""
        tricky = "it's \"$x\" \\ `y`"
        pairs = [("127.0.0.1", 11434), ("127.0.0.2", 8000)]
        words = " ".join(map(launch.sh_literal, (tricky, pairs, 11434)))
        run = subprocess.run(
            [BUSYBOX, "sh", "-c", f"printf '%s\\n' {words}"],
            capture_output=True,
            encoding="utf-8",
            timeout=10,
        )
        self.assertEqual(
            run.stdout.splitlines(), [tricky, "127.0.0.1:11434 127.0.0.2:8000", "11434"]
        )


if __name__ == "__main__":
    unittest.main()
