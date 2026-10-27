"""Run wire.php's own tests, and compare its frames with wire.py's byte for byte."""

import json
import subprocess
import unittest
from pathlib import Path

from hello_127 import launch, wire
from tests.test_tunnel import PHP

TESTS = Path(__file__).parent
WIRE_PHP = Path(wire.__file__).with_suffix(".php").read_text(encoding="utf-8")


def run_php(script):
    """Run wire.php's source, then `script`, and return its stdout."""
    run = subprocess.run(
        [PHP, "-r", f"{WIRE_PHP}\n{script}"],
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )
    if run.returncode != 0:
        raise AssertionError(run.stderr)
    return run.stdout


@unittest.skipUnless(PHP, "php not on PATH")
class PhpTest(unittest.TestCase):
    """wire.php on its own, through php."""

    def test_php_test_suite(self):
        """`php tests/test_wire.php` passes; its output is the message if not."""
        run = subprocess.run(
            [PHP, str(TESTS / "test_wire.php")],
            capture_output=True,
            encoding="utf-8",
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
            f"foreach ({launch.php_literal([[k, c, p.hex()] for k, c, p in cases])}"
            " as [$kind, $conn, $hex])\n"
            "    echo bin2hex(frame($kind, $conn, hex2bin($hex))), \"\\n\";\n"
        )
        expected = [wire.frame(kind, conn, payload).hex() for kind, conn, payload in cases]
        self.assertEqual(run_php(script).split(), expected)

    def test_literal_round_trips(self):
        """An argument with `$`, quotes, and a backslash reaches PHP unchanged."""
        value = ["a$b", "it's", 'say "hi"', "back\\slash", [["127.0.0.1", 80]]]
        script = f"echo json_encode({launch.php_literal(value)});"
        self.assertEqual(json.loads(run_php(script)), value)


if __name__ == "__main__":
    unittest.main()
