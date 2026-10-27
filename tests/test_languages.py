"""Pin the `languages` command: its grammar, its rows, and its exit codes."""

import json
import unittest
from unittest import mock

from hello_127 import args, cli, cli_languages, launch
from tests.test_cli import found, missing, run_cli


class LanguagesGrammarTest(unittest.TestCase):
    """`languages RUNTIME CONTAINER` reads the same two slots as the other commands."""

    def test_bare_word_prints_its_page(self):
        """`languages` alone answers with its docstring, then its own --help."""
        code, out, _ = run_cli("languages")
        self.assertEqual(code, cli.EXIT_OK)
        help_text = args.command_help(args.add_languages).rstrip()
        self.assertTrue(out.rstrip().endswith(help_text))
        self.assertIn("hello-127 -- Languages", out)

    def test_help_starts_with_usage(self):
        """`languages --help` opens on its own usage line."""
        code, out, _ = run_cli("languages", "--help")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertTrue(out.startswith(f"usage: {cli_languages.USAGE}"))

    def test_root_usage_lists_it(self):
        """The root usage carries the command's line, before `version`."""
        _, out, _ = run_cli()
        self.assertIn(cli_languages.USAGE, out)
        self.assertLess(out.index(cli_languages.USAGE), out.index("hello-127 version"))

    def test_missing_container(self):
        """A runtime with no container names both slots and the usage line."""
        code, _, err = run_cli("languages", "docker")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("languages needs both RUNTIME and CONTAINER", err)
        self.assertIn(f"Usage: {cli_languages.USAGE}", err)

    def test_stray_word(self):
        """A word past CONTAINER is refused before anything runs."""
        with mock.patch.object(cli_languages, "run") as run:
            code, _, err = run_cli("languages", "docker", "h127", "extra")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("languages takes nothing after CONTAINER: 'extra'", err)
        run.assert_not_called()

    def test_no_languages_flag(self):
        """It checks every language, so `--languages` is an unknown flag, exit 2."""
        with mock.patch.object(cli_languages, "run") as run:
            code, _, err = run_cli("languages", "docker", "h127", "--languages", "node")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("unrecognized arguments: --languages", err)
        run.assert_not_called()


class LanguagesReportTest(unittest.TestCase):
    """What the rows say for each probe answer."""

    def languages(self, answers, runtime="docker", image=found("debian:bookworm-slim\n")):
        """Run `languages` with inspect answering `image`, then the probes `answers`.

        Return (code, out, err). The inspect command is kept apart from the probes.
        """
        answers = answers if isinstance(answers, list) else [answers]
        with mock.patch("subprocess.run", side_effect=[image, *answers]) as exec_:
            result = run_cli("languages", runtime, "h127")
        commands = [call.args[0] for call in exec_.call_args_list]
        self.inspect, self.probes = commands[0], commands[1:]
        return result

    def test_one_row_each_in_order(self):
        """The image line, then every language probed in order, each a padded row."""
        code, out, err = self.languages(
            [
                missing("python3"), found("18.19.0\n"), found("5.36.0\n"), missing("ruby"),
                missing("php"), found("1.35.0\nthe full nc\n"),
            ]
        )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(
            out,
            "container h127 runs debian:bookworm-slim\n"
            "python   ---\n"
            "node     node 18.19.0 (needs 20 or newer)\n"
            "perl     perl 5.36.0\n"
            "ruby     ---\n"
            "php      ---\n"
            "busybox  busybox 1.35.0 (needs 1.36 or newer and the full nc)\n",
        )
        self.assertEqual(err, "")
        self.assertEqual(
            [probe[3] for probe in self.probes],
            [language.interpreter[0] for language in launch.LANGUAGES.values()],
        )

    def test_probes_without_i(self):
        """Each probe is a plain exec, with no `-i`."""
        self.languages([missing("x")] * len(launch.LANGUAGES))
        for probe in self.probes:
            self.assertEqual(probe[:3], ["docker", "exec", "h127"])

    def test_nothing_fits_is_still_ok(self):
        """An image with no usable language is an answer, exit 0."""
        code, out, _ = self.languages(
            [missing(language.interpreter[0]) for language in launch.LANGUAGES.values()]
        )
        self.assertEqual(code, cli.EXIT_OK)
        rows = out.splitlines()[1:]
        self.assertEqual(rows, [f"{language:<7}  ---" for language in launch.LANGUAGES])

    def test_apple_container_missing_is_a_dash(self):
        """Apple Container's stderr-only miss reads as `---` too, not as a failure."""
        miss = mock.Mock(
            returncode=1, stdout="", stderr="Error: failed to find target executable node\n"
        )
        reference = {"configuration": {"image": {"reference": "docker.io/library/python:3.12"}}}
        code, out, _ = self.languages(
            [found("3.12\n"), miss, *[found("9.9\n")] * (len(launch.LANGUAGES) - 2)],
            runtime="container",
            image=found(json.dumps([reference])),
        )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(out.splitlines()[2], "node     ---")

    def test_docker_inspects_the_container(self):
        """Docker is asked with `container inspect`, so an image name is no such container."""
        self.languages([missing("x")] * len(launch.LANGUAGES))
        self.assertEqual(
            self.inspect,
            ["docker", "container", "inspect", "--format", "{{.Config.Image}}", "h127"],
        )

    def test_apple_container_full_reference(self):
        """Apple Container's JSON gives the full reference, printed as it is."""
        reference = {"configuration": {"image": {"reference": "docker.io/library/busybox:1.37"}}}
        code, out, _ = self.languages(
            [found("1.37.0\n")] * len(launch.LANGUAGES),
            runtime="container",
            image=found(json.dumps([reference])),
        )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(self.inspect, ["container", "inspect", "h127"])
        self.assertEqual(out.splitlines()[0], "container h127 runs docker.io/library/busybox:1.37")

    def test_no_such_container_probes_nothing(self):
        """An image name, or any name the runtime cannot find, stops before any probe."""
        absent = mock.Mock(
            returncode=1, stdout="", stderr="Error response from daemon: No such container: h127\n"
        )
        code, out, err = self.languages([], image=absent)
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertEqual(out, "")
        self.assertEqual(
            err, "hello-127: docker: Error response from daemon: No such container: h127\n"
        )
        self.assertEqual(self.probes, [])

    def test_stopped_container_prints_no_rows(self):
        """A probe failure past the first language is exit 1, with nothing on stdout."""
        stopped = mock.Mock(
            returncode=1, stdout="", stderr="Error response from daemon: container is not running\n"
        )
        code, out, err = self.languages([found("3.12\n"), stopped])
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertEqual(out, "")
        self.assertEqual(
            err, "hello-127: docker: Error response from daemon: container is not running\n"
        )

    def test_runtime_not_on_path(self):
        """A runtime that is not installed is a readiness error, at the inspect."""
        code, out, err = self.languages([], runtime="container", image=FileNotFoundError())
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertEqual(out, "")
        self.assertEqual(err, "hello-127: container is not on PATH\n")


if __name__ == "__main__":
    unittest.main()
