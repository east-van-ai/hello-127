"""Run wire.js's own tests, and compare its frames with wire.py's byte for byte."""

import json
import subprocess
import unittest
from pathlib import Path

from hello_127 import wire
from tests.test_tunnel import NODE

TESTS = Path(__file__).parent
WIRE_JS = Path(wire.__file__).with_suffix(".js")


@unittest.skipUnless(NODE, "node not on PATH")
class JavaScriptTest(unittest.TestCase):
    """wire.js on its own, through node."""

    def test_node_test_suite(self):
        """`node --test tests/test_wire.js` passes; its output is the message if not."""
        run = subprocess.run(
            [NODE, "--test", str(TESTS / "test_wire.js")],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)

    def test_frames_match_python(self):
        """Both files write the same bytes for every kind, payload, and edge number."""
        cases = [
            (kind, conn, payload)
            for kind in (wire.OPEN, wire.DATA, wire.CLOSE)
            for conn in (1, 2**32 - 1)
            for payload in (b"", b"\x00hello\xff")
        ]
        script = (
            f"const wire = require({json.dumps(str(WIRE_JS))});\n"
            f"const cases = {json.dumps([[k, c, p.hex()] for k, c, p in cases])};\n"
            "for (const [kind, conn, hex] of cases)\n"
            "  console.log(wire.frame(kind, conn, Buffer.from(hex, 'hex')).toString('hex'));\n"
        )
        run = subprocess.run(
            [NODE, "-e", script], capture_output=True, text=True, timeout=60
        )
        self.assertEqual(run.returncode, 0, run.stderr)
        expected = [wire.frame(kind, conn, payload).hex() for kind, conn, payload in cases]
        self.assertEqual(run.stdout.split(), expected)


if __name__ == "__main__":
    unittest.main()
