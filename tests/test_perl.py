"""Run wire.pl's own tests, and compare its frames with wire.py's byte for byte."""

import json
import subprocess
import unittest
from pathlib import Path

from hello_127 import launch, wire
from tests.test_tunnel import PERL, PERL_SKIP

TESTS = Path(__file__).parent
WIRE_PL = Path(wire.__file__).with_suffix(".pl").read_text(encoding="utf-8")


def run_perl(script):
    """Run wire.pl's source, then `script`, and return its stdout."""
    run = subprocess.run(
        [PERL, "-e", f"{WIRE_PL}\n{script}"],
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )
    if run.returncode != 0:
        raise AssertionError(run.stderr)
    return run.stdout


@unittest.skipUnless(PERL, PERL_SKIP)
class PerlTest(unittest.TestCase):
    """wire.pl on its own, through perl."""

    def test_perl_test_suite(self):
        """`perl tests/test_wire.pl` passes; its output is the message if not."""
        run = subprocess.run(
            [PERL, str(TESTS / "test_wire.pl")],
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
            f"for my $case (@{{{launch.perl_literal([[k, c, p.hex()] for k, c, p in cases])}}}) {{\n"
            "    my ($kind, $conn, $hex) = @$case;\n"
            "    print unpack('H*', frame($kind, $conn, pack('H*', $hex))), \"\\n\";\n"
            "}\n"
        )
        expected = [wire.frame(kind, conn, payload).hex() for kind, conn, payload in cases]
        self.assertEqual(run_perl(script).split(), expected)

    def test_literal_round_trips(self):
        """An argument with `$`, `@`, quotes, and a backslash reaches Perl unchanged."""
        value = ["$x @y", "it's", 'say "hi"', "back\\slash", "end\\", [["127.0.0.1", 80]]]
        script = (
            "sub show { my ($v) = @_; return ref $v\n"
            "  ? '[' . join(',', map { show($_) } @$v) . ']'\n"
            "  : $v =~ /\\A\\d+\\z/ ? $v\n"
            "  : '\"' . join('', map { sprintf '\\\\u%04x', ord } split //, $v) . '\"' }\n"
            f"print show({launch.perl_literal(value)});\n"
        )
        self.assertEqual(json.loads(run_perl(script)), value)


if __name__ == "__main__":
    unittest.main()
