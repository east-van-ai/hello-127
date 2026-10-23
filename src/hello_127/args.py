"""The command line's vocabulary: the parser, its subparsers, and the version line."""
import argparse
import ipaddress
import sys
from collections import namedtuple
from importlib import metadata

from hello_127 import cli_query, cli_tunnel, launch

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
"""Where the helper listens inside, and what the Mac dials for each connection."""

Endpoint = namedtuple("Endpoint", "address port")
"""An address and a port, for `ollama-query` to dial inside the container."""

DEFAULT_FORWARD = Forward(LOOPBACK, OLLAMA_PORT, LOOPBACK, OLLAMA_PORT)
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


class StoreOnce(argparse.Action):
    """Store a flag's value, and refuse the flag given a second time."""

    def __call__(self, parser, namespace, values, option_string=None):
        """Store `values`, unless an earlier occurrence already replaced the default."""
        if getattr(namespace, self.dest) is not self.default:
            raise argparse.ArgumentError(self, "given more than once")
        setattr(namespace, self.dest, values)


class AppendForward(argparse.Action):
    """Collect each --forward in order, and refuse a listener given twice."""

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


def add_tunnel(subparsers):
    """Add the `tunnel` subparser and return it."""
    tunnel = add_runtime_slots(
        subparsers.add_parser(
            "tunnel", help=cli_tunnel.HELP, usage=cli_tunnel.USAGE, allow_abbrev=False
        )
    )
    tunnel.add_argument(
        "--forward",
        type=forward_spec,
        action=AppendForward,
        default=[DEFAULT_FORWARD],
        dest="forwards",
        metavar="SPEC",
        help="listen on BIND:PORT inside and dial HOST:HOSTPORT on the Mac, "
        "as [BIND:]PORT:HOST:HOSTPORT, all loopback; repeat for more "
        "(default: 127.0.0.1:11434:127.0.0.1:11434)",
    )
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
    return query


def build_parser():
    """Build the top-level parser with every command."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        usage="\n       ".join([cli_tunnel.USAGE, cli_query.USAGE, f"{PROG} version"]),
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
    subparsers.add_parser(
        "version", help="print the installed version and exit", allow_abbrev=False
    )
    return parser


def command_help(add_command):
    """Return one command's own `--help` text, as argparse prints it."""
    subparsers = argparse.ArgumentParser(prog=PROG, **MONOCHROME).add_subparsers()
    return add_command(subparsers).format_help()
