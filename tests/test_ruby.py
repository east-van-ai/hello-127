"""Run wire.rb's own tests, and compare its frames with wire.py's byte for byte."""

import json
import subprocess
import unittest
from pathlib import Path

from hello_127 import launch, wire
from tests.test_tunnel import RUBY, RUBY_SKIP

TESTS = Path(__file__).parent
WIRE_RB = Path(wire.__file__).with_suffix(".rb").read_text(encoding="utf-8")


def run_ruby(script):
    """Run wire.rb's source, then `script`, and return its stdout."""
    run = subprocess.run(
        [RUBY, "-e", f"{WIRE_RB}\n{script}"],
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )
    if run.returncode != 0:
        raise AssertionError(run.stderr)
    return run.stdout


@unittest.skipUnless(RUBY, RUBY_SKIP)
class RubyTest(unittest.TestCase):
    """wire.rb on its own, through ruby."""

    def test_ruby_test_suite(self):
        """`ruby tests/test_wire.rb` passes; its output is the message if not."""
        run = subprocess.run(
            [RUBY, str(TESTS / "test_wire.rb")],
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
            f"{launch.ruby_literal([[k, c, p.hex()] for k, c, p in cases])}"
            ".each do |kind, conn, hex|\n"
            "  puts frame(kind, conn, [hex].pack('H*')).unpack1('H*')\n"
            "end\n"
        )
        expected = [wire.frame(kind, conn, payload).hex() for kind, conn, payload in cases]
        self.assertEqual(run_ruby(script).split(), expected)

    def test_literal_round_trips(self):
        """An argument with `#{}`, quotes, and a backslash reaches Ruby unchanged."""
        value = ["a#{b}", "it's", 'say "hi"', "back\\slash", [["127.0.0.1", 80]]]
        script = f"puts JSON.generate({launch.ruby_literal(value)})"
        self.assertEqual(json.loads(run_ruby(script)), value)


if __name__ == "__main__":
    unittest.main()
