"""
# ==============================================
# East Van AI -- AI for the rest of us!
# https://github.com/east-van-ai/hello-127
# contact: east-van-ai@proton.me
# license: MIT
# ==============================================

        hello-127

Carries TCP over a container's standard streams, so a container with no
network reaches Ollama on the Mac's 127.0.0.1. A helper inside listens on
127.0.0.1:11434; this side dials Ollama for every connection it reports.
Reach for `tunnel`, then `ollama-query` to try it.

Run a command with nothing after it for its own page.

piped input:
    hello-127 reads none.

exit codes:
    0:     success, and documentation
    1:     hello-127's own error: a missing CONTAINER, a stray word after it,
           the runtime not on PATH, or the helper or the query exiting
           with an error
    2:     an unknown command, an unknown option, or a bad value
"""
import sys
from collections import namedtuple

from hello_127 import args, cli_query, cli_tunnel, errors

# argparse exits 2 itself, so EXIT_ARGPARSE never returns through main.
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ARGPARSE = 2


def command_page(module, add_command):
    """Return a command's answer to its bare word: its docstring, then its --help."""
    doc = module.__doc__.strip("\n")  # not strip(): the title's indent is layout
    return f"{doc}\n\n{args.command_help(add_command).rstrip()}"


Command = namedtuple("Command", "bare usage slots action")
"""A command word's answer to being typed alone, its usage line, the path slots it
reads, and the action a full invocation runs.

`bare` returns the text for the bare word; `action` runs the command. For `version`,
both read from `version_line`, since running the command answers the bare word.
"""

COMMANDS = {
    "tunnel": Command(
        lambda: command_page(cli_tunnel, args.add_tunnel),
        cli_tunnel.USAGE,
        cli_tunnel.SLOTS,
        lambda paths, parsed: cli_tunnel.run(*paths, parsed),
    ),
    "ollama-query": Command(
        lambda: command_page(cli_query, args.add_ollama_query),
        cli_query.USAGE,
        cli_query.SLOTS,
        lambda paths, parsed: cli_query.run(*paths, parsed),
    ),
    "version": Command(
        args.version_line,
        "hello-127 version",
        (),
        lambda paths, parsed: print(args.version_line()),
    ),
}


def usage_error(usage, message):
    """Report a command line the tool could not read, with the matching usage."""
    sys.stdout.flush()
    print(f"hello-127: {message}", file=sys.stderr)
    print(f"Usage: {usage}", file=sys.stderr)
    return EXIT_ERROR


def readiness_error(message):
    """Report what the run needed and did not find, with no usage line."""
    sys.stdout.flush()
    print(f"hello-127: {message}", file=sys.stderr)
    return EXIT_ERROR


def runtime_error(message):
    """Report a run that stopped partway, naming what was written."""
    sys.stdout.flush()
    print(f"hello-127: {message}", file=sys.stderr)
    return EXIT_ERROR


def main(argv=None):
    """Parse arguments, run the matching command, return an exit code."""
    tokens = list(sys.argv[1:] if argv is None else argv)

    if not tokens:
        print(f"{__doc__.strip()}\n\n{args.build_parser().format_help().rstrip()}")
        return EXIT_OK

    # A command word and nothing else is a question, and its own page answers.
    if len(tokens) == 1 and tokens[0] in COMMANDS:
        print(COMMANDS[tokens[0]].bare())
        return EXIT_OK

    parser = args.build_parser()
    parsed, extras = parser.parse_known_args(tokens)

    if any(extra.startswith("-") for extra in extras):
        parser.parse_args(tokens)  # argparse names the flag better, exit 2

    paths = args.leading_paths(tokens[1:])

    command = COMMANDS[parsed.command]

    if len(paths) < len(command.slots):
        needed = " and ".join(command.slots)
        if len(command.slots) > 1:
            needed = f"both {needed}"
        return usage_error(command.usage, f"{parsed.command} needs {needed}")

    # A word past the slots is a stray, and so is one argparse left over after a flag.
    strays = paths[len(command.slots) :] or extras
    if strays:
        last = command.slots[-1] if command.slots else "it"
        return usage_error(
            command.usage,
            f"{parsed.command} takes nothing after {last}: {strays[0]!r}",
        )

    try:
        command.action(paths, parsed)
    except errors.ReadinessError as failure:
        return readiness_error(str(failure))
    except errors.RuntimeFailure as failure:
        return runtime_error(str(failure))

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
