"""The command line's vocabulary: the parser, its subparsers, and the version line."""
import argparse
import ipaddress
import sys
from collections import namedtuple
from importlib import metadata

from hello_127 import cli_languages, cli_query, cli_tunnel, launch

PROG = "hello-127"

PATHS = """\
paths:
  RUNTIME   `docker` or `container`, the runtime that runs CONTAINER.
  CONTAINER the name or id of a running container.
  RUNTIME and CONTAINER come right after COMMAND, then options in any order."""

MONOCHROME = {"color": False} if sys.version_info >= (3, 14) else {}

LOOPBACK = "127.0.0.1"
OLLAMA_PORT = 11434

Forward = namedtuple("Forward", "bind port host hostport")
"""A listener and its target: for `--out`, the helper listens and the Mac dials;
for `--in`, the Mac listens and the helper dials."""

Endpoint = namedtuple("Endpoint", "address port")
"""An address and a port, for `ollama-query` to dial inside the container."""

DEFAULT_ENDPOINT = Endpoint(LOOPBACK, OLLAMA_PORT)


def leading_paths(tokens):
    """Return the tokens ahead of the first flag."""
    paths = []
    for token in tokens:
        if token.startswith("-"):
            break
        paths.append(token)
    return paths


def installed_version():
    """Return the version of the installed hello-127 distribution."""
    try:
        return metadata.version("hello-127")
    except metadata.PackageNotFoundError:
        return "unknown (not installed)"


def version_line():
    """Return the program name and the installed version on one line."""
    return f"{PROG} {installed_version()}"


def loopback(text):
    """Return `text` as a loopback IPv4 address, or refuse it as a bad value."""
    try:
        address = ipaddress.IPv4Address(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an IPv4 address: {text!r}") from None
    if not address.is_loopback:
        raise argparse.ArgumentTypeError(f"not a loopback address: {text!r}")
    return str(address)


def port_number(text):
    """Return `text` as a TCP port from 1 to 65535, or refuse it as a bad value."""
    if not (text.isascii() and text.isdigit() and 0 < int(text) < 65536):
        raise argparse.ArgumentTypeError(f"not a port: {text!r}")
    return int(text)


def forward_spec(text):
    """Read `[BIND:]PORT:HOST:HOSTPORT` into a Forward. BIND defaults to loopback."""
    parts = text.split(":")
    if len(parts) == 3:
        parts.insert(0, LOOPBACK)
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(f"expected [BIND:]PORT:HOST:HOSTPORT: {text!r}")
    bind, port, host, hostport = parts
    return Forward(loopback(bind), port_number(port), loopback(host), port_number(hostport))


def endpoint_spec(text):
    """Read `ADDRESS:PORT` into an Endpoint."""
    parts = text.split(":")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"expected ADDRESS:PORT: {text!r}")
    address, port = parts
    return Endpoint(loopback(address), port_number(port))


def language_list(text):
    """Read `NAME[,NAME]...` into a tuple of languages, in the order to try them."""
    names = tuple(text.split(","))
    for name in names:
        if name not in launch.LANGUAGES:
            raise argparse.ArgumentTypeError(
                f"not a language: {name!r}; choose from {','.join(launch.LANGUAGES)}"
            )
        if names.count(name) > 1:
            raise argparse.ArgumentTypeError(f"{name} given twice")
    return names


class StoreOnce(argparse.Action):
    """Store a flag's value, and refuse the flag given a second time.

    The flags already stored are kept on the namespace. Comparing the value against
    the default misses a repeat whose first occurrence names the default.
    """

    def __call__(self, parser, namespace, values, option_string=None):
        """Store `values`, unless an earlier occurrence already stored one."""
        stored = vars(namespace).setdefault("stored_once", set())
        if self.dest in stored:
            raise argparse.ArgumentError(self, "given more than once")
        stored.add(self.dest)
        setattr(namespace, self.dest, values)


class AppendForward(argparse.Action):
    """Collect each --out or --in in order, and refuse a listener given twice."""

    def __call__(self, parser, namespace, values, option_string=None):
        """Append `values`, starting a fresh list in place of the default."""
        forwards = getattr(namespace, self.dest)
        if forwards is self.default:
            forwards = []
        if any(forward[:2] == values[:2] for forward in forwards):
            raise argparse.ArgumentError(
                self, f"listener {values.bind}:{values.port} given twice"
            )
        setattr(namespace, self.dest, [*forwards, values])


def add_runtime_slots(command):
    """Add the RUNTIME and CONTAINER positionals that both commands read."""
    paths = command.add_argument_group("paths")
    paths.add_argument(
        "runtime",
        nargs="?",
        choices=sorted(launch.EXEC),
        metavar="RUNTIME",
        help="`docker` or `container`",
    )
    paths.add_argument(
        "container", nargs="?", metavar="CONTAINER", help="a running container"
    )
    return command


def add_languages_flag(command, what):
    """Add `--languages`, the languages to try for the `what` sent into the container."""
    command.add_argument(
        "--languages",
        type=language_list,
        action=StoreOnce,
        default=tuple(launch.LANGUAGES),
        metavar="LIST",
        help=f"the languages to try for the {what} in the container, in order, "
        f"comma-separated (default: {','.join(launch.LANGUAGES)})",
    )


def add_tunnel(subparsers):
    """Add the `tunnel` subparser and return it."""
    tunnel = add_runtime_slots(
        subparsers.add_parser(
            "tunnel", help=cli_tunnel.HELP, usage=cli_tunnel.USAGE, allow_abbrev=False
        )
    )
    tunnel.add_argument(
        "--out",
        type=forward_spec,
        action=AppendForward,
        default=[],
        dest="outs",
        metavar="SPEC",
        help="listen inside, dial the Mac: [BIND:]PORT:HOST:HOSTPORT, BIND:PORT "
        "inside and HOST:HOSTPORT on the Mac, all loopback; repeat for more",
    )
    tunnel.add_argument(
        "--in",
        type=forward_spec,
        action=AppendForward,
        default=[],
        dest="ins",
        metavar="SPEC",
        help="listen on the Mac, dial inside: [BIND:]PORT:HOST:HOSTPORT, BIND:PORT "
        "on the Mac and HOST:HOSTPORT inside, all loopback; repeat for more",
    )
    add_languages_flag(tunnel, "helper")
    return tunnel


def add_ollama_query(subparsers):
    """Add the `ollama-query` subparser and return it."""
    query = add_runtime_slots(
        subparsers.add_parser(
            "ollama-query",
            help=cli_query.HELP,
            usage=cli_query.USAGE,
            allow_abbrev=False,
        )
    )
    query.add_argument(
        "--connect",
        type=endpoint_spec,
        action=StoreOnce,
        default=DEFAULT_ENDPOINT,
        metavar="ADDRESS:PORT",
        help="where the tunnel listens inside, loopback (default: 127.0.0.1:11434)",
    )
    add_languages_flag(query, "query")
    return query


def add_languages(subparsers):
    """Add the `languages` subparser and return it."""
    return add_runtime_slots(
        subparsers.add_parser(
            "languages",
            help=cli_languages.HELP,
            usage=cli_languages.USAGE,
            allow_abbrev=False,
        )
    )


def build_parser():
    """Build the top-level parser with every command."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        usage="\n       ".join(
            [cli_tunnel.USAGE, cli_query.USAGE, cli_languages.USAGE, f"{PROG} version"]
        ),
        epilog=PATHS,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
        **MONOCHROME,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=version_line(),
        help="print the installed version and exit",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    add_tunnel(subparsers)
    add_ollama_query(subparsers)
    add_languages(subparsers)
    subparsers.add_parser(
        "version", help="print the installed version and exit", allow_abbrev=False
    )
    return parser


def command_help(add_command):
    """Return one command's own `--help` text, as argparse prints it."""
    subparsers = argparse.ArgumentParser(prog=PROG, **MONOCHROME).add_subparsers()
    return add_command(subparsers).format_help()
