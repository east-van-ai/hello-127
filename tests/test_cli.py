"""Pin the command line: what each shape of input prints and returns."""

import contextlib
import io
import unittest
from unittest import mock

from hello_127 import args, cli, cli_query, cli_tunnel, launch, wire


def run_cli(*argv):
    """Run the tool and return (code, stdout, stderr), whether it returns or exits."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as exit:
            code = exit.code
    return code, out.getvalue(), err.getvalue()


OLLAMA_OUT = ("--out", "11434:127.0.0.1:11434")


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

    def test_no_forward(self):
        """Neither --out nor --in is a grammar error, before anything runs."""
        with mock.patch.object(cli_tunnel, "run") as run:
            code, _, err = run_cli("tunnel", "docker", "h127")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("tunnel needs at least one --out or --in", err)
        self.assertIn(f"Usage: {cli_tunnel.USAGE}", err)
        run.assert_not_called()

    def test_languages_alone_is_no_forward(self):
        """--languages is not a forward, so the tunnel still needs one."""
        with mock.patch.object(cli_tunnel, "run") as run:
            code, _, err = run_cli("tunnel", "docker", "h127", "--languages", "node")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("tunnel needs at least one --out or --in", err)
        run.assert_not_called()

    def test_runtime_words_are_not_commands(self):
        """`docker` is a RUNTIME now, not a command word."""
        code, _, err = run_cli("docker", "h127")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("invalid choice: 'docker'", err)

    def test_full_invocation_reaches_the_action(self):
        """Both slots filled runs the tunnel with them, in order."""
        with mock.patch.object(cli_tunnel, "run") as run:
            code, _, _ = run_cli("tunnel", "container", "h127", *OLLAMA_OUT)
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(run.call_args.args[:2], ("container", "h127"))


class OutTest(unittest.TestCase):
    """`tunnel --out SPEC`: the shapes it takes, and the ones it refuses."""

    def both(self, *flags):
        """Run the tunnel's grammar with `flags`, and return the (outs, ins) it reached."""
        with mock.patch.object(cli_tunnel, "run") as run:
            code, _, err = run_cli("tunnel", "docker", "h127", *flags)
        self.assertEqual(code, cli.EXIT_OK, err)
        parsed = run.call_args.args[2]
        return parsed.outs, parsed.ins

    def forwards(self, *flags):
        """Run the tunnel's grammar with `flags`, and return the `--out`s it reached."""
        return self.both(*flags)[0]

    def forward(self, spec):
        """Run the tunnel's grammar with one `spec`, and return its Forward."""
        (forward,) = self.forwards("--out", spec)
        return forward

    def refused(self, *flags):
        """Run the tunnel's grammar with `flags`, and return (code, stderr)."""
        with mock.patch.object(cli_tunnel, "run") as run:
            code, _, err = run_cli("tunnel", "docker", "h127", *flags)
        run.assert_not_called()
        return code, err

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
        code, err = self.refused("--out", "8080:10.0.0.5:11434")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("not a loopback address: '10.0.0.5'", err)

    def test_bind_off_loopback(self):
        """A BIND of 0.0.0.0 is a bad value too."""
        code, err = self.refused("--out", "0.0.0.0:8080:127.0.0.1:11434")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("not a loopback address: '0.0.0.0'", err)

    def test_hostname(self):
        """A name is not an address, not even localhost."""
        code, err = self.refused("--out", "8080:localhost:11434")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("not an IPv4 address: 'localhost'", err)

    def test_bad_port(self):
        """A port past 65535 is a bad value."""
        code, err = self.refused("--out", "8080:127.0.0.1:99999")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("not a port: '99999'", err)

    def test_short_spec(self):
        """Two parts is not a spec, and the message shows the shape."""
        code, err = self.refused("--out", "8080:11434")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("expected [BIND:]PORT:HOST:HOSTPORT: '8080:11434'", err)

    def test_several_in_order(self):
        """Each --out is kept, in the order given."""
        self.assertEqual(
            self.forwards(
                "--out", "8080:127.0.0.1:8000", "--out", "11434:127.0.0.1:11434"
            ),
            [
                args.Forward("127.0.0.1", 8080, "127.0.0.1", 8000),
                args.Forward("127.0.0.1", 11434, "127.0.0.1", 11434),
            ],
        )

    def test_shared_target(self):
        """Two listeners may dial the same target."""
        forwards = self.forwards(
            "--out", "80:127.0.0.1:11434", "--out", "8080:127.0.0.1:11434"
        )
        self.assertEqual(len(forwards), 2)

    def test_listener_twice(self):
        """Two forwards on one BIND:PORT is a bad value, exit 2, naming it."""
        code, err = self.refused(
            "--out", "80:127.0.0.1:11434", "--out", "127.0.0.1:80:127.0.0.1:8000"
        )
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("argument --out: listener 127.0.0.1:80 given twice", err)

    def test_same_port_on_two_aliases(self):
        """127.0.0.1:80 and 127.0.0.2:80 are two listeners."""
        forwards = self.forwards(
            "--out", "80:127.0.0.1:11434", "--out", "127.0.0.2:80:127.0.0.1:8000"
        )
        self.assertEqual(len(forwards), 2)

    def test_stray_word_after_the_flag(self):
        """A bare word behind --out's value is a stray, before anything runs."""
        code, err = self.refused("--out", "8080:127.0.0.1:11434", "extra")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("tunnel takes nothing after CONTAINER: 'extra'", err)
        self.assertIn(f"Usage: {cli_tunnel.USAGE}", err)

    def test_forward_is_gone(self):
        """`--forward` is an unknown option now, exit 2."""
        code, err = self.refused("--forward", "8080:127.0.0.1:11434")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("unrecognized arguments: --forward", err)


class InTest(OutTest):
    """`tunnel --in SPEC`: the Mac listens, and the helper dials inside."""

    test_forward_is_gone = None

    def forwards(self, *flags):
        """Run the tunnel's grammar with `flags` as `--in`, and return the `--in`s."""
        return self.both(*self.as_in(flags))[1]

    def forward(self, spec):
        """Run the tunnel's grammar with one `--in spec`, and return its Forward."""
        (forward,) = self.forwards("--out", spec)
        return forward

    def refused(self, *flags):
        """Run the tunnel's grammar with `flags` as `--in`, and return (code, stderr)."""
        code, err = super().refused(*self.as_in(flags))
        return code, err.replace("argument --in:", "argument --out:")

    @staticmethod
    def as_in(flags):
        """Return `flags` with each `--out` turned into `--in`, so OutTest's cases rerun."""
        return ["--in" if flag == "--out" else flag for flag in flags]

    def test_out_alone_has_no_in(self):
        """`--out` alone listens on nothing on the Mac."""
        self.assertEqual(self.both(*OLLAMA_OUT)[1], [])

    def test_in_alone_listens_on_nothing_inside(self):
        """`--in` alone listens on nothing inside."""
        outs, ins = self.both("--in", "8080:127.0.0.1:8000")
        self.assertEqual(outs, [])
        self.assertEqual(ins, [args.Forward("127.0.0.1", 8080, "127.0.0.1", 8000)])

    def test_both_flags_in_any_order(self):
        """`--in` then `--out` keeps both, each in its own list."""
        outs, ins = self.both(
            "--in", "8080:127.0.0.1:8000", "--out", "11434:127.0.0.1:11434"
        )
        self.assertEqual(outs, [args.Forward("127.0.0.1", 11434, "127.0.0.1", 11434)])
        self.assertEqual(ins, [args.Forward("127.0.0.1", 8080, "127.0.0.1", 8000)])

    def test_out_and_in_share_a_listener(self):
        """An `--out` and an `--in` on one BIND:PORT bind on two machines, so both stand."""
        outs, ins = self.both("--out", "80:127.0.0.1:11434", "--in", "80:127.0.0.1:8000")
        self.assertEqual((len(outs), len(ins)), (1, 1))


def found(version):
    """Return a probe's answer from an interpreter that printed `version`."""
    return mock.Mock(returncode=0, stdout=version, stderr="")


def missing(interpreter):
    """Return Docker's answer to a probe of an interpreter the image lacks."""
    return mock.Mock(
        returncode=127,
        stdout="OCI runtime exec failed: exec failed: unable to start container "
        f'process: exec: "{interpreter}": executable file not found in $PATH\n',
        stderr="",
    )


class LanguagesTest(unittest.TestCase):
    """`tunnel --languages LIST`: the languages to try for the helper, in order."""

    def languages(self, *flags):
        """Run the tunnel's grammar with `flags`, and return the languages it reached."""
        with mock.patch.object(cli_tunnel, "run") as run:
            code, _, err = run_cli("tunnel", "docker", "h127", *OLLAMA_OUT, *flags)
        self.assertEqual(code, cli.EXIT_OK, err)
        return run.call_args.args[2].languages

    def refused(self, *flags):
        """Run the tunnel's grammar with `flags`, and return (code, stderr)."""
        with mock.patch.object(cli_tunnel, "run") as run:
            code, _, err = run_cli("tunnel", "docker", "h127", *flags)
        run.assert_not_called()
        return code, err

    def test_default_tries_every_language(self):
        """No --languages tries all six, Perl third, then Ruby, PHP, and BusyBox last."""
        self.assertEqual(
            self.languages(), ("python", "node", "perl", "ruby", "php", "busybox")
        )

    def test_one_name(self):
        """One name tries only that language."""
        self.assertEqual(self.languages("--languages", "ruby"), ("ruby",))

    def test_list_keeps_its_order(self):
        """A list reaches the tunnel in the order given."""
        self.assertEqual(self.languages("--languages", "php,ruby"), ("php", "ruby"))

    def test_unknown_language(self):
        """A name outside launch.LANGUAGES is a bad value that lists the choices."""
        code, err = self.refused("--languages", "ruby,cobol")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("not a language: 'cobol'; choose from python,node,perl,ruby,php,busybox\n", err)

    def test_javascript_is_not_a_choice(self):
        """The choice names what runs, so JavaScript is `node`, and `javascript` is refused."""
        code, err = self.refused("--languages", "javascript")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("not a language: 'javascript'; choose from python,node,", err)

    def test_empty_name(self):
        """A trailing comma leaves an empty name, a bad value."""
        code, err = self.refused("--languages", "ruby,")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("not a language: ''", err)

    def test_repeated_name(self):
        """A name given twice in the list is a bad value."""
        code, err = self.refused("--languages", "ruby,php,ruby")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("ruby given twice", err)

    def test_bare_flag(self):
        """--languages with no list is refused, not read as trying nothing."""
        code, err = self.refused("--languages")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("argument --languages: expected one argument", err)

    def test_given_twice(self):
        """--languages twice is refused, even when the first names the default."""
        code, err = self.refused(
            "--languages", "python,node,ruby,php", "--languages", "ruby"
        )
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("argument --languages: given more than once", err)

    def test_stray_word_after_the_flag(self):
        """A bare word behind --languages's value is a stray, before anything runs."""
        code, err = self.refused("--languages", "node", "extra")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("tunnel takes nothing after CONTAINER: 'extra'", err)
        self.assertIn(f"Usage: {cli_tunnel.USAGE}", err)

    def test_node_exec_line(self):
        """The JavaScript helper runs as `node -e`, with its listeners as JSON."""
        program = launch.source(wire, "listen", [("127.0.0.1", 80)], [("127.0.0.1", 8000)], language="node")
        command = launch.exec_command(
            "docker", "h127", program, language="node", interactive=True
        )
        self.assertEqual(command[:5], ["docker", "exec", "-i", "h127", "node"])
        self.assertEqual(command[5], "-e")
        self.assertTrue(program.endswith('\nlisten([["127.0.0.1", 80]], [["127.0.0.1", 8000]])\n'))

    def test_php_exec_line(self):
        """The PHP helper runs as `php -r`, its listeners decoded from JSON, then `;`."""
        program = launch.source(wire, "listen", [("127.0.0.1", 80)], [("127.0.0.1", 8000)], language="php")
        command = launch.exec_command(
            "docker", "h127", program, language="php", interactive=True
        )
        self.assertEqual(command[:6], ["docker", "exec", "-i", "h127", "php", "-r"])
        self.assertTrue(
            program.endswith(
                "\nlisten(json_decode('[[\"127.0.0.1\", 80]]', true),"
                " json_decode('[[\"127.0.0.1\", 8000]]', true));\n"
            )
        )

    def test_perl_exec_line(self):
        """The Perl helper runs as `perl -e`, its listeners as Perl data, called with `&`."""
        program = launch.source(wire, "listen", [("127.0.0.1", 80)], [("127.0.0.1", 8000)], language="perl")
        command = launch.exec_command(
            "docker", "h127", program, language="perl", interactive=True
        )
        self.assertEqual(command[:6], ["docker", "exec", "-i", "h127", "perl", "-e"])
        self.assertTrue(
            program.endswith("\n&listen([['127.0.0.1', 80]], [['127.0.0.1', 8000]])\n")
        )

    def test_ruby_exec_line(self):
        """The Ruby helper runs as `ruby -e`, its listeners parsed from JSON."""
        program = launch.source(wire, "listen", [("127.0.0.1", 80)], [("127.0.0.1", 8000)], language="ruby")
        command = launch.exec_command(
            "docker", "h127", program, language="ruby", interactive=True
        )
        self.assertEqual(command[:6], ["docker", "exec", "-i", "h127", "ruby", "-e"])
        self.assertTrue(
            program.endswith(
                """\nlisten(JSON.parse('[["127.0.0.1", 80]]'), JSON.parse('[["127.0.0.1", 8000]]'))\n"""
            )
        )

    def test_python_exec_line(self):
        """The Python helper still runs as `python3 -c`, with its listeners as repr."""
        program = launch.source(wire, "listen", [("127.0.0.1", 80)], [("127.0.0.1", 8000)])
        command = launch.exec_command("docker", "h127", program, interactive=True)
        self.assertEqual(command[:6], ["docker", "exec", "-i", "h127", "python3", "-c"])
        self.assertTrue(program.endswith("\nlisten([('127.0.0.1', 80)], [('127.0.0.1', 8000)])\n"))

    def test_busybox_exec_line(self):
        """The BusyBox helper runs as `busybox sh -c`, its listeners and targets as words."""
        program = launch.source(
            wire, "listen", [("127.0.0.1", 80), ("127.0.0.2", 81)], [("127.0.0.1", 8000)],
            language="busybox",
        )
        command = launch.exec_command(
            "docker", "h127", program, language="busybox", interactive=True
        )
        self.assertEqual(command[:7], ["docker", "exec", "-i", "h127", "busybox", "sh", "-c"])
        self.assertTrue(program.endswith("\nlisten '127.0.0.1:80 127.0.0.2:81' '127.0.0.1:8000'\n"))


class DetectionTest(unittest.TestCase):
    """The walk before the tunnel: which language each run of probe answers picks."""

    def tunnel(self, *flags, answers, runtime="docker"):
        """Run `tunnel` with the probes answering `answers` in turn. Return (code, stderr).

        The tunnel itself is mocked, and must start only when a language fits.
        """
        with (
            mock.patch("subprocess.run", side_effect=answers) as exec_,
            mock.patch.object(
                cli_tunnel.host, "run_until_signal", new_callable=mock.Mock
            ) as tunnel,
            mock.patch("asyncio.run", return_value=(0, True)),
        ):
            code, _, err = run_cli("tunnel", runtime, "h127", *OLLAMA_OUT, *flags)
        self.started = tunnel.called
        self.helper = tunnel.call_args.args[0] if tunnel.called else None
        self.probes = [call.args[0] for call in exec_.call_args_list]
        return code, err

    def test_python_first(self):
        """A python3 past the floor wins at once, probed without -i, and is named."""
        code, err = self.tunnel(answers=[found("3.12\n")])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(err, "hello-127: tunnel uses python3 3.12 in container h127\n")
        self.assertEqual(len(self.probes), 1)
        self.assertEqual(self.probes[0][:5], ["docker", "exec", "h127", "python3", "-c"])
        self.assertEqual(self.helper[3:6], ["h127", "python3", "-c"])

    def test_perl_only_container(self):
        """Python and Node missing, the walk reaches Perl and sends the Perl helper."""
        code, err = self.tunnel(
            answers=[missing("python3"), missing("node"), found("5.36.0\n")]
        )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(err, "hello-127: tunnel uses perl 5.36.0 in container h127\n")
        self.assertEqual([probe[3] for probe in self.probes], ["python3", "node", "perl"])
        self.assertEqual(self.helper[3:6], ["h127", "perl", "-e"])

    def test_ruby_only_container(self):
        """Python, Node, and Perl missing, the walk reaches Ruby and sends its helper."""
        code, err = self.tunnel(
            answers=[missing("python3"), missing("node"), missing("perl"), found("3.3\n")]
        )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(err, "hello-127: tunnel uses ruby 3.3 in container h127\n")
        self.assertEqual(
            [probe[3] for probe in self.probes], ["python3", "node", "perl", "ruby"]
        )
        self.assertEqual(self.helper[3:6], ["h127", "ruby", "-e"])

    def test_php_after_ruby(self):
        """A PHP-only container is reached last, after Ruby misses."""
        code, err = self.tunnel(
            answers=[
                missing("python3"), missing("node"), missing("perl"), missing("ruby"), found("8.2")
            ]
        )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(err, "hello-127: tunnel uses php 8.2 in container h127\n")
        self.assertEqual(self.helper[3:6], ["h127", "php", "-r"])

    def test_busybox_last(self):
        """An image with no interpreter is reached last, and gets the BusyBox helper."""
        code, err = self.tunnel(
            answers=[
                missing("python3"), missing("node"), missing("perl"), missing("ruby"),
                missing("php"), found("1.37.0\n"),
            ]
        )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(err, "hello-127: tunnel uses busybox 1.37.0 in container h127\n")
        self.assertEqual(self.probes[-1][3:6], ["busybox", "sh", "-c"])
        self.assertEqual(self.helper[3:7], ["h127", "busybox", "sh", "-c"])

    def test_cut_down_busybox_names_the_nc(self):
        """A BusyBox whose nc has no `-s`, as Ubuntu ships, names its version and the nc."""
        code, err = self.tunnel(
            "--languages", "busybox", answers=[found("1.36.1\nthe full nc\n")]
        )
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertEqual(
            err,
            "hello-127: container h127 has no interpreter tunnel can use: "
            "busybox 1.36.1 (needs the full nc)\n",
        )
        self.assertFalse(self.started)

    def test_floor_and_nc_both_named(self):
        """Debian's BusyBox is below the floor and lacks the full nc: both needs, in order."""
        code, err = self.tunnel(
            "--languages", "busybox", answers=[found("1.35.0\nthe full nc\n")]
        )
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertEqual(
            err,
            "hello-127: container h127 has no interpreter tunnel can use: "
            "busybox 1.35.0 (needs 1.36 or newer and the full nc)\n",
        )

    def test_too_old_moves_on(self):
        """A node below its floor moves on to the next language."""
        code, err = self.tunnel(
            "--languages", "node,python", answers=[found("18.19.0\n"), found("3.12\n")]
        )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(err, "hello-127: tunnel uses python3 3.12 in container h127\n")
        self.assertEqual(self.helper[4], "python3")

    def test_nothing_fits(self):
        """No language left is one line with every note, in the order tried."""
        code, err = self.tunnel(
            answers=[
                missing("python3"), found("18.19.0\n"), missing("perl"), missing("ruby"),
                missing("php"), missing("busybox"),
            ]
        )
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertEqual(
            err,
            "hello-127: container h127 has no interpreter tunnel can use: "
            "no python3, node 18.19.0 (needs 20 or newer), no perl, no ruby, no php, "
            "no busybox\n",
        )
        self.assertFalse(self.started)

    def test_each_floor(self):
        """Each language, pinned and one step below its floor, names the floor."""
        for language, version, note in (
            ("python", "3.9\n", "python3 3.9 (needs 3.10 or newer)"),
            ("node", "18.19.0\n", "node 18.19.0 (needs 20 or newer)"),
            ("perl", "5.32.1\n", "perl 5.32.1 (needs 5.34 or newer)"),
            ("ruby", "2.6\n", "ruby 2.6 (needs 3.3 or newer)"),
            ("php", "8.1", "php 8.1 (needs 8.2 or newer)"),
            ("busybox", "1.35.0\n", "busybox 1.35.0 (needs 1.36 or newer)"),
        ):
            with self.subTest(language=language):
                code, err = self.tunnel("--languages", language, answers=[found(version)])
                self.assertEqual(code, cli.EXIT_ERROR)
                self.assertEqual(
                    err,
                    f"hello-127: container h127 has no interpreter tunnel can use: {note}\n",
                )
                self.assertFalse(self.started)

    def test_each_probe(self):
        """Each language, pinned, probes its own interpreter and sends its own helper."""
        for language, version, interpreter in (
            ("node", "20.20.2\n", ["node", "-e"]),
            ("perl", "5.34.1\n", ["perl", "-e"]),
            ("ruby", "3.3\n", ["ruby", "-e"]),
            ("php", "8.2", ["php", "-r"]),
            ("busybox", "1.36.1\n", ["busybox", "sh"]),
        ):
            with self.subTest(language=language):
                code, _ = self.tunnel("--languages", language, answers=[found(version)])
                self.assertEqual(code, cli.EXIT_OK)
                self.assertEqual([probe[3:5] for probe in self.probes], [interpreter])
                self.assertEqual(self.helper[4:6], interpreter)

    def test_pinned_and_missing(self):
        """One name that is missing probes only itself, and says so."""
        code, err = self.tunnel("--languages", "node", answers=[missing("node")])
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertEqual(
            err, "hello-127: container h127 has no interpreter tunnel can use: no node\n"
        )
        self.assertEqual(len(self.probes), 1)

    def test_order_given_is_order_probed(self):
        """`php,ruby` probes php first, and stops there when it fits."""
        code, err = self.tunnel("--languages", "php,ruby", answers=[found("8.2")])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual([probe[3] for probe in self.probes], ["php"])

    def test_missing_on_apple_container(self):
        """Apple Container's exit 1 naming the executable moves on, like Docker's 127."""
        apple_missing = mock.Mock(
            returncode=1,
            stdout="",
            stderr="Error: failed to find target executable python3\n"
            "Error: failed to start process ...\n",
        )
        code, err = self.tunnel(
            answers=[apple_missing, found("20.20.2\n")], runtime="container"
        )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(err, "hello-127: tunnel uses node 20.20.2 in container h127\n")
        self.assertEqual(self.probes[1][:4], ["container", "exec", "h127", "node"])

    def test_not_running_stops_the_walk(self):
        """Any other failure relays the runtime's first line after one probe."""
        stopped = mock.Mock(
            returncode=1,
            stdout="",
            stderr="Error response from daemon: No such container: h127\n",
        )
        code, err = self.tunnel(answers=[stopped])
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertEqual(
            err, "hello-127: docker: Error response from daemon: No such container: h127\n"
        )
        self.assertEqual(len(self.probes), 1)
        self.assertFalse(self.started)

    def test_not_a_version_stops_the_walk(self):
        """An answer that is not a version is shown, not guessed at, and not walked past."""
        code, err = self.tunnel(answers=[found("Python is not configured\n")])
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertEqual(err, "hello-127: docker: Python is not configured\n")
        self.assertEqual(len(self.probes), 1)
        self.assertFalse(self.started)

    def test_runtime_not_on_path(self):
        """No docker on PATH is a readiness error before anything runs."""
        with (
            mock.patch("subprocess.run", side_effect=FileNotFoundError),
            mock.patch("asyncio.run", side_effect=FileNotFoundError),
        ):
            code, _, err = run_cli("tunnel", "docker", "h127", *OLLAMA_OUT)
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertEqual(err, "hello-127: docker is not on PATH\n")


class QueryCheckTest(unittest.TestCase):
    """The same walk before `ollama-query`, naming that command."""

    def query(self, *flags, answers, query_code=0):
        """Run `ollama-query` with the probes answering `answers`. Return (code, stderr)."""
        ran = mock.Mock(returncode=query_code)
        with mock.patch("subprocess.run", side_effect=[*answers, ran]) as exec_:
            code, _, err = run_cli("ollama-query", "docker", "h127", *flags)
        self.calls = [call.args[0] for call in exec_.call_args_list]
        return code, err

    def test_missing_python(self):
        """No python3 is one line naming ollama-query, and the query never runs."""
        code, err = self.query("--languages", "python", answers=[missing("python3")])
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertEqual(
            err,
            "hello-127: container h127 has no interpreter ollama-query can use: "
            "no python3\n",
        )
        self.assertEqual(len(self.calls), 1)

    def test_ok_runs_the_query(self):
        """A python3 past the floor runs the query after the probe."""
        code, err = self.query(answers=[found("3.12\n")])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(
            err, "hello-127: ollama-query uses python3 3.12 in container h127\n"
        )
        self.assertEqual(self.calls[0][3:5], ["python3", "-c"])
        self.assertEqual(len(self.calls), 2)

    def test_perl_only_runs_perl(self):
        """With no python3 or node, the walk reaches Perl and runs query.pl."""
        code, err = self.query(answers=[missing("python3"), missing("node"), found("5.36.0\n")])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(err, "hello-127: ollama-query uses perl 5.36.0 in container h127\n")
        self.assertEqual(self.calls[-1][3:5], ["perl", "-e"])
        self.assertTrue(self.calls[-1][5].endswith("\n&ask('127.0.0.1', 11434)\n"))

    def test_ruby_only_runs_ruby(self):
        """With no python3, node, or perl, the walk reaches Ruby and runs query.rb."""
        code, err = self.query(
            answers=[missing("python3"), missing("node"), missing("perl"), found("3.3\n")]
        )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(err, "hello-127: ollama-query uses ruby 3.3 in container h127\n")
        self.assertEqual(self.calls[-1][3:5], ["ruby", "-e"])

    def test_busybox_only_runs_busybox(self):
        """With no interpreter at all, the walk reaches BusyBox and runs query.sh."""
        code, err = self.query(
            "--languages", "busybox", answers=[found("1.37.0\n")]
        )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(err, "hello-127: ollama-query uses busybox 1.37.0 in container h127\n")
        self.assertEqual(self.calls[-1][3:6], ["busybox", "sh", "-c"])
        self.assertTrue(self.calls[-1][6].endswith("\nask '127.0.0.1' '11434'\n"))


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


class QueryLanguagesTest(unittest.TestCase):
    """`ollama-query --languages LIST`: the languages to try for the query."""

    def refused(self, *flags):
        """Run the query's grammar with `flags`, and return (code, stderr)."""
        with mock.patch.object(cli_query, "run") as run:
            code, _, err = run_cli("ollama-query", "docker", "h127", *flags)
        run.assert_not_called()
        return code, err

    def languages(self, *flags):
        """Run the query's grammar with `flags`, and return the languages it reached."""
        with mock.patch.object(cli_query, "run") as run:
            code, _, err = run_cli("ollama-query", "docker", "h127", *flags)
        self.assertEqual(code, cli.EXIT_OK, err)
        return run.call_args.args[2].languages

    def test_default_tries_every_language(self):
        """No --languages tries all six, Perl third, then Ruby, PHP, and BusyBox last."""
        self.assertEqual(
            self.languages(), ("python", "node", "perl", "ruby", "php", "busybox")
        )

    def test_list_reaches_the_action(self):
        """A list reaches the query in the order given."""
        self.assertEqual(self.languages("--languages", "ruby,php"), ("ruby", "php"))

    def test_unknown_language(self):
        """A language outside launch.LANGUAGES is a bad value, exit 2."""
        code, err = self.refused("--languages", "cobol")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("not a language: 'cobol'", err)

    def test_given_twice(self):
        """--languages twice is refused."""
        code, err = self.refused("--languages", "python", "--languages", "node")
        self.assertEqual(code, cli.EXIT_ARGPARSE)
        self.assertIn("argument --languages: given more than once", err)

    def test_stray_word_after_the_flag(self):
        """A bare word behind --languages's value is a stray, before anything runs."""
        code, err = self.refused("--languages", "node", "extra")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertIn("ollama-query takes nothing after CONTAINER: 'extra'", err)
        self.assertIn(f"Usage: {cli_query.USAGE}", err)

    def test_node_runs_node(self):
        """--languages node checks node, then runs query.js with `node -e`."""
        checked = mock.Mock(returncode=0, stdout="20.20.2\n", stderr="")
        ran = mock.Mock(returncode=0)
        with mock.patch("subprocess.run", side_effect=[checked, ran]) as exec_:
            code, _, err = run_cli(
                "ollama-query", "docker", "h127", "--languages", "node"
            )
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(err, "hello-127: ollama-query uses node 20.20.2 in container h127\n")
        probe, query_command = (call.args[0] for call in exec_.call_args_list)
        self.assertEqual(probe[3:5], ["node", "-e"])
        self.assertEqual(query_command[:5], ["docker", "exec", "h127", "node", "-e"])
        self.assertTrue(query_command[5].endswith('\nask("127.0.0.1", 11434)\n'))

    def test_php_runs_php(self):
        """--languages php checks php, then runs query.php with `php -r`."""
        checked = mock.Mock(returncode=0, stdout="8.2", stderr="")
        ran = mock.Mock(returncode=0)
        with mock.patch("subprocess.run", side_effect=[checked, ran]) as exec_:
            code, _, err = run_cli("ollama-query", "docker", "h127", "--languages", "php")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(err, "hello-127: ollama-query uses php 8.2 in container h127\n")
        probe, query_command = (call.args[0] for call in exec_.call_args_list)
        self.assertEqual(probe[3:5], ["php", "-r"])
        self.assertEqual(query_command[:5], ["docker", "exec", "h127", "php", "-r"])
        self.assertTrue(
            query_command[5].endswith(
                """\nask(json_decode('"127.0.0.1"', true), json_decode('11434', true));\n"""
            )
        )

    def test_ruby_runs_ruby(self):
        """--languages ruby checks ruby, then runs query.rb with `ruby -e`."""
        checked = mock.Mock(returncode=0, stdout="3.3\n", stderr="")
        ran = mock.Mock(returncode=0)
        with mock.patch("subprocess.run", side_effect=[checked, ran]) as exec_:
            code, _, err = run_cli("ollama-query", "docker", "h127", "--languages", "ruby")
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(err, "hello-127: ollama-query uses ruby 3.3 in container h127\n")
        probe, query_command = (call.args[0] for call in exec_.call_args_list)
        self.assertEqual(probe[3:5], ["ruby", "-e"])
        self.assertEqual(query_command[:5], ["docker", "exec", "h127", "ruby", "-e"])
        self.assertTrue(
            query_command[5].endswith(
                """\nask(JSON.parse('"127.0.0.1"'), JSON.parse('11434'))\n"""
            )
        )


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
        checked = mock.Mock(returncode=0, stdout="3.12\n", stderr="")
        failed = mock.Mock(returncode=1)
        with mock.patch("subprocess.run", side_effect=[checked, failed]):
            code, _, err = run_cli("ollama-query", "docker", "h127")
        self.assertEqual(code, cli.EXIT_ERROR)
        self.assertEqual(
            err,
            "hello-127: ollama-query uses python3 3.12 in container h127\n"
            "hello-127: the query exited with code 1\n",
        )


if __name__ == "__main__":
    unittest.main()
