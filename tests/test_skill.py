"""Keep the agent skill in step with the command line."""

import pathlib
import re
import shlex
import unittest
from unittest import mock

from hello_127 import cli, cli_languages, cli_query, cli_tunnel, launch

from tests.test_cli import run_cli

SKILL = pathlib.Path(__file__).resolve().parent.parent / "skills" / "hello-127" / "SKILL.md"

RUNS = {"tunnel": cli_tunnel, "ollama-query": cli_query, "languages": cli_languages}


def skill_text():
    """Return the skill file as text."""
    return SKILL.read_text(encoding="utf-8")


def skill_commands(text):
    """Return each `hello-127` command in the skill's bash fences, continuations joined."""
    commands = []
    for fence in re.findall(r"```bash\n(.*?)```", text, re.DOTALL):
        for line in fence.replace("\\\n", " ").splitlines():
            if line.startswith("hello-127 "):
                commands.append(shlex.split(line)[1:])
    return commands


class SkillTest(unittest.TestCase):
    """The skill opens with its frontmatter, and every command in it parses."""

    def test_frontmatter(self):
        """The file opens with `name: hello-127` and a description."""
        head = skill_text().split("---\n")[1]
        self.assertIn("name: hello-127\n", head)
        self.assertRegex(head, r"description: \S")

    def test_every_command_parses(self):
        """Each command reaches its own `run`, exit 0."""
        commands = skill_commands(skill_text())
        self.assertEqual({argv[0] for argv in commands}, set(RUNS))
        for argv in commands:
            with self.subTest(argv=" ".join(argv)):
                with mock.patch.object(RUNS[argv[0]], "run", return_value=cli.EXIT_OK) as run:
                    code, _, err = run_cli(*argv)
                self.assertEqual(code, cli.EXIT_OK, err)
                run.assert_called_once()

    def test_default_order(self):
        """The skill names the default order of `launch.LANGUAGES`."""
        self.assertIn(",".join(launch.LANGUAGES), skill_text())

    def test_ascii(self):
        """The skill stays ASCII, like the rest of what a model is handed."""
        self.assertTrue(SKILL.read_bytes().isascii())


if __name__ == "__main__":
    unittest.main()
