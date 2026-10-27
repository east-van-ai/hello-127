"""Keep the programs sent into a container safe to launch from Windows."""

import subprocess
import sys
import unittest
from pathlib import Path

from hello_127 import launch, query, wire

BUDGET = 32_767 // 2
STRICT_ENCODING = """
from hello_127 import errors, launch, query, shared, wire
for language in launch.LANGUAGES:
    launch.source(wire, "listen", [], [], language=language)
    launch.source(query, "ask", "127.0.0.1", 11434, language=language)
    try:
        shared.probe("docker", "h127", language)
    except errors.ReadinessError:
        pass
"""
PROGRAMS = (
    (wire, "listen", ([("127.0.0.1", 11434)], [("127.0.0.1", 8000)])),
    (query, "ask", ("127.0.0.1", 11434)),
)


CALLS = {
    "python": (
        "listen([('127.0.0.1', 11434)], [('127.0.0.1', 8000)])",
        "ask('127.0.0.1', 11434)",
    ),
    "node": (
        'listen([["127.0.0.1", 11434]], [["127.0.0.1", 8000]])',
        'ask("127.0.0.1", 11434)',
    ),
    "perl": (
        "&listen([['127.0.0.1', 11434]], [['127.0.0.1', 8000]])",
        "&ask('127.0.0.1', 11434)",
    ),
    "ruby": (
        """listen(JSON.parse('[["127.0.0.1", 11434]]'), JSON.parse('[["127.0.0.1", 8000]]'))""",
        """ask(JSON.parse('"127.0.0.1"'), JSON.parse('11434'))""",
    ),
    "php": (
        """listen(json_decode('[["127.0.0.1", 11434]]', true), """
        """json_decode('[["127.0.0.1", 8000]]', true));""",
        """ask(json_decode('"127.0.0.1"', true), json_decode('11434', true));""",
    ),
    "busybox": (
        "listen '127.0.0.1:11434' '127.0.0.1:8000'",
        "ask '127.0.0.1' '11434'",
    ),
}


class CallTest(unittest.TestCase):
    """The one call after each program, written in its own language."""

    def test_call_lines(self):
        """Each language's last line is its call, with the arguments as its literals."""
        for language, expected in CALLS.items():
            for (module, entry, arguments), line in zip(PROGRAMS, expected):
                with self.subTest(language=language, program=module.__name__):
                    program = launch.source(module, entry, *arguments, language=language)
                    self.assertEqual(program.splitlines()[-1], line)


class WindowsTest(unittest.TestCase):
    """What Windows asks of the exec command and the files it carries."""

    def test_command_line_fits_half_the_cap(self):
        """Each exec command, escaped as Windows sees it, stays under half of 32,767."""
        for language in launch.LANGUAGES:
            for module, entry, arguments in PROGRAMS:
                with self.subTest(language=language, program=module.__name__):
                    program = launch.source(module, entry, *arguments, language=language)
                    command = launch.exec_command(
                        "docker", "h127", program, language=language, interactive=True
                    )
                    length = len(subprocess.list2cmdline(command))
                    self.assertLessEqual(
                        length, BUDGET, f"{module.__name__} in {language} is {length}"
                    )

    def test_programs_are_ascii(self):
        """Each container program is pure ASCII, since the container decodes it in its locale."""
        for language in launch.LANGUAGES.values():
            for module, _, _ in PROGRAMS:
                path = Path(module.__file__).with_suffix(language.suffix)
                with self.subTest(file=path.name):
                    lines = path.read_bytes().splitlines()
                    wrong = [number for number, line in enumerate(lines, 1) if not line.isascii()]
                    if wrong:
                        self.fail(f"{path.name} has non-ASCII on line {wrong[0]}")

    def test_reads_name_utf_8(self):
        """Reading a program and the interpreter check's reply never fall back to the locale.

        The child turns a missing `encoding` into an error. Its `PATH` is empty, so the
        check never reaches a container.
        """
        flags = ["-X", "warn_default_encoding", "-W", "error::EncodingWarning"]
        child = subprocess.run(
            [sys.executable, *flags, "-c", STRICT_ENCODING],
            capture_output=True,
            encoding="utf-8",
            env={"PATH": ""},
        )
        self.assertEqual(child.returncode, 0, child.stderr)
