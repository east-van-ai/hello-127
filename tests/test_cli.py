"""Pin the command line: what each shape of input prints and returns."""

import contextlib
import io
import unittest
from unittest import mock

from hello_127 import args, cli, cli_query, cli_tunnel


def run_cli(*argv):
    """Run the tool and return (code, stdout, stderr), whether it returns or exits."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as exit:
            code = exit.code
    return code, out.getvalue(), err.getvalue()


class TunnelGrammarTest(unittest.TestCase):
    """`tunnel RUNTIME CONTAINER`, and every way to get it wrong."""

    def test_bare_word_prints_its_page(self):
        """`tunnel` alone answers with its docstring, then its own --help."""
        code, out, _ = run_cli("tunnel")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertTrue(out.rstrip().endswith(args.command_help(args.add_tunnel).rstrip()))
        self.assertIn("hello-127 -- Tunnel", out)

    def test_unknown_runtime_is_a_bad_value(self):
        """A runtime other than docker or container is argparse's, exit 2."""
        code, _, err = run_cli("tunnel", "podman", "h127")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("invalid choice: 'podman'", err)

    def test_missing_container(self):
        """A runtime with no container names both slots and the usage line."""
        code, _, err = run_cli("tunnel", "docker")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("tunnel needs both RUNTIME and CONTAINER", err)
        self.assertIn(f"Usage: {cli_tunnel.USAGE}", err)

    def test_stray_word(self):
        """A word past CONTAINER is refused before anything runs."""
        with mock.patch.object(cli_tunnel, "run") as run:
            code, _, err = run_cli("tunnel", "docker", "h127", "extra")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("tunnel takes nothing after CONTAINER: 'extra'", err)
        run.assert_not_called()

    def test_runtime_words_are_not_commands(self):
        """`docker` is a RUNTIME now, not a command word."""
        code, _, err = run_cli("docker", "h127")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("invalid choice: 'docker'", err)

    def test_full_invocation_reaches_the_action(self):
        """Both slots filled runs the tunnel with them, in order."""
        with mock.patch.object(cli_tunnel, "run") as run:
            code, _, _ = run_cli("tunnel", "container", "h127")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(run.call_args.args[:2], ("container", "h127"))


class ForwardTest(unittest.TestCase):
    """`tunnel --forward SPEC`: the shapes it takes, and the ones it refuses."""

    def forwards(self, *flags):
        """Run the tunnel's grammar with `flags`, and return the forwards it reached."""
        with mock.patch.object(cli_tunnel, "run") as run:
            code, _, err = run_cli("tunnel", "docker", "h127", *flags)
        self.assertEqual(code, cli.EXIT_OK, err)
        return run.call_args.args[2].forwards

    def forward(self, spec):
        """Run the tunnel's grammar with one `spec`, and return its Forward."""
        (forward,) = self.forwards("--forward", spec)
        return forward

    def refused(self, *flags):
        """Run the tunnel's grammar with `flags`, and return (code, stderr)."""
        with mock.patch.object(cli_tunnel, "run") as run:
            code, _, err = run_cli("tunnel", "docker", "h127", *flags)
        run.assert_not_called()
        return code, err

    def test_default_is_ollama_both_ends(self):
        """No --forward listens on 127.0.0.1:11434 and dials 127.0.0.1:11434."""
        self.assertEqual(
            self.forwards(), [args.Forward("127.0.0.1", 11434, "127.0.0.1", 11434)]
        )

    def test_three_parts_bind_loopback(self):
        """PORT:HOST:HOSTPORT listens on 127.0.0.1."""
        self.assertEqual(
            self.forward("8080:127.0.0.1:11434"),
            args.Forward("127.0.0.1", 8080, "127.0.0.1", 11434),
        )

    def test_four_parts(self):
        """BIND:PORT:HOST:HOSTPORT keeps every part."""
        self.assertEqual(
            self.forward("127.0.0.1:80:127.0.0.2:11434"),
            args.Forward("127.0.0.1", 80, "127.0.0.2", 11434),
        )

    def test_host_off_loopback(self):
        """A HOST off loopback is a bad value, exit 2, naming the address."""
        code, err = self.refused("--forward", "8080:10.0.0.5:11434")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("not a loopback address: '10.0.0.5'", err)

    def test_bind_off_loopback(self):
        """A BIND of 0.0.0.0 is a bad value too."""
        code, err = self.refused("--forward", "0.0.0.0:8080:127.0.0.1:11434")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("not a loopback address: '0.0.0.0'", err)

    def test_hostname(self):
        """A name is not an address, not even localhost."""
        code, err = self.refused("--forward", "8080:localhost:11434")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("not an IPv4 address: 'localhost'", err)

    def test_bad_port(self):
        """A port past 65535 is a bad value."""
        code, err = self.refused("--forward", "8080:127.0.0.1:99999")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("not a port: '99999'", err)

    def test_short_spec(self):
        """Two parts is not a spec, and the message shows the shape."""
        code, err = self.refused("--forward", "8080:11434")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("expected [BIND:]PORT:HOST:HOSTPORT: '8080:11434'", err)

    def test_one_replaces_the_default(self):
        """One --forward is the only forward, not added to the default."""
        self.assertEqual(
            self.forwards("--forward", "8080:127.0.0.1:8000"),
            [args.Forward("127.0.0.1", 8080, "127.0.0.1", 8000)],
        )

    def test_several_in_order(self):
        """Each --forward is kept, in the order given."""
        self.assertEqual(
            self.forwards(
                "--forward", "8080:127.0.0.1:8000", "--forward", "11434:127.0.0.1:11434"
            ),
            [
                args.Forward("127.0.0.1", 8080, "127.0.0.1", 8000),
                args.Forward("127.0.0.1", 11434, "127.0.0.1", 11434),
            ],
        )

    def test_shared_target(self):
        """Two listeners may dial the same target."""
        forwards = self.forwards(
            "--forward", "80:127.0.0.1:11434", "--forward", "8080:127.0.0.1:11434"
        )
        self.assertEqual(len(forwards), 2)

    def test_listener_twice(self):
        """Two forwards on one BIND:PORT is a bad value, exit 2, naming it."""
        code, err = self.refused(
            "--forward", "80:127.0.0.1:11434", "--forward", "127.0.0.1:80:127.0.0.1:8000"
        )
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("argument --forward: listener 127.0.0.1:80 given twice", err)

    def test_same_port_on_two_aliases(self):
        """127.0.0.1:80 and 127.0.0.2:80 are two listeners."""
        forwards = self.forwards(
            "--forward", "80:127.0.0.1:11434", "--forward", "127.0.0.2:80:127.0.0.1:8000"
        )
        self.assertEqual(len(forwards), 2)

    def test_stray_word_after_the_flag(self):
        """A bare word behind --forward's value is a stray, before anything runs."""
        code, err = self.refused("--forward", "8080:127.0.0.1:11434", "extra")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("tunnel takes nothing after CONTAINER: 'extra'", err)
        self.assertIn(f"Usage: {cli_tunnel.USAGE}", err)


class ConnectTest(unittest.TestCase):
    """`ollama-query --connect ADDRESS:PORT`."""

    def test_default_is_ollama(self):
        """No --connect dials 127.0.0.1:11434."""
        with mock.patch.object(cli_query, "run") as run:
            run_cli("ollama-query", "docker", "h127")
        self.assertEqual(run.call_args.args[2].connect, args.Endpoint("127.0.0.1", 11434))

    def test_reaches_the_action(self):
        """ADDRESS:PORT reaches the query as an Endpoint."""
        with mock.patch.object(cli_query, "run") as run:
            code, _, _ = run_cli(
                "ollama-query", "docker", "h127", "--connect", "127.0.0.2:80"
            )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(run.call_args.args[2].connect, args.Endpoint("127.0.0.2", 80))

    def test_off_loopback(self):
        """An address off loopback is a bad value, exit 2."""
        with mock.patch.object(cli_query, "run") as run:
            code, _, err = run_cli(
                "ollama-query", "docker", "h127", "--connect", "10.0.0.5:80"
            )
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("not a loopback address: '10.0.0.5'", err)
        run.assert_not_called()

    def test_stray_word_after_the_flag(self):
        """A bare word behind --connect's value is a stray, before anything runs."""
        with mock.patch.object(cli_query, "run") as run:
            code, _, err = run_cli(
                "ollama-query", "docker", "h127", "--connect", "127.0.0.1:80", "extra"
            )
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("ollama-query takes nothing after CONTAINER: 'extra'", err)
        run.assert_not_called()


class OllamaQueryGrammarTest(unittest.TestCase):
    """`ollama-query RUNTIME CONTAINER` reads the same two slots as `tunnel`."""

    def test_bare_word_prints_its_page(self):
        """`ollama-query` alone answers with its docstring, then its own --help."""
        code, out, _ = run_cli("ollama-query")
        self.assertEqual(code, cli.EXIT_OK)
        help_text = args.command_help(args.add_ollama_query).rstrip()
        self.assertTrue(out.rstrip().endswith(help_text))
        self.assertIn("hello-127 -- Ollama Query", out)

    def test_unknown_runtime_is_a_bad_value(self):
        """A runtime other than docker or container is argparse's, exit 2."""
        code, _, err = run_cli("ollama-query", "podman", "h127")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("invalid choice: 'podman'", err)

    def test_missing_container(self):
        """A runtime with no container names both slots and the usage line."""
        code, _, err = run_cli("ollama-query", "docker")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("ollama-query needs both RUNTIME and CONTAINER", err)
        self.assertIn(f"Usage: {cli_query.USAGE}", err)

    def test_stray_word(self):
        """A word past CONTAINER is refused before anything runs."""
        with mock.patch.object(cli_query, "run") as run:
            code, _, err = run_cli("ollama-query", "docker", "h127", "extra")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("ollama-query takes nothing after CONTAINER: 'extra'", err)
        run.assert_not_called()

    def test_full_invocation_reaches_the_action(self):
        """Both slots filled runs the query with them, in order."""
        with mock.patch.object(cli_query, "run") as run:
            code, _, _ = run_cli("ollama-query", "docker", "h127")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(run.call_args.args[:2], ("docker", "h127"))

    def test_query_exit_code_is_reported(self):
        """A query that fails inside the container is hello-127's exit 1."""
        failed = mock.Mock(returncode=1)
        with mock.patch("subprocess.run", return_value=failed):
            code, _, err = run_cli("ollama-query", "docker", "h127")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertEqual(err, "hello-127: the query exited with code 1\n")


if __name__ == "__main__":
    unittest.main()
