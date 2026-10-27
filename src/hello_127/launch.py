"""The exec commands that run a program from this package inside a container."""

import json
from collections import namedtuple
from pathlib import Path

EXEC = {"docker": ["docker", "exec"], "container": ["container", "exec"]}

Language = namedtuple("Language", "interpreter suffix literal call sep probe floor")
"""How a container runs a program: the interpreter and its flag for inline source,
the program file's suffix, how to write an argument as a literal, and how to write
the one call after the file. `call` is a format string over `entry` and `args`, the
literals joined by `sep`. Perl needs `&` before the call, since `listen` is a Perl
built-in, and PHP needs a semicolon after it.

`probe` is inline source that prints the interpreter's version, written to run on
interpreters far older than `floor`, the oldest version the helper supports. Any
further line it prints names one more thing the helper needs and the image lacks,
such as BusyBox's `the full nc`.
"""


def single_quoted_json(value):
    """Return `value`'s JSON in single quotes, for PHP and Ruby alike.

    A double-quoted string expands `$` in PHP and `#{}` in Ruby. In single quotes,
    both languages read only a backslash and a quote as escapes.
    """
    text = json.dumps(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{text}'"


def php_literal(value):
    """Return `value` as a PHP expression: its single-quoted JSON, decoded."""
    return f"json_decode({single_quoted_json(value)}, true)"


def ruby_literal(value):
    """Return `value` as a Ruby expression: its single-quoted JSON, parsed."""
    return f"JSON.parse({single_quoted_json(value)})"


def perl_literal(value):
    """Return `value` as Perl data: lists as array refs, strings in single quotes.

    The `perl-base` in slim images has no JSON module. In single quotes, Perl reads
    only a backslash and a quote as escapes, so `$` and `@` stay as they are.
    """
    if isinstance(value, (list, tuple)):
        return f"[{', '.join(map(perl_literal, value))}]"
    if isinstance(value, int):
        return str(value)
    text = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{text}'"


def sh_literal(value):
    """Return `value` as one single-quoted shell word.

    A list of (address, port) pairs becomes `'A:P A:P'`, which the BusyBox helper
    splits on spaces. Inside single quotes, sh reads nothing as an escape, so a quote
    closes the word, adds an escaped quote, and opens it again.
    """
    if isinstance(value, (list, tuple)):
        value = " ".join(f"{address}:{port}" for address, port in value)
    text = str(value).replace("'", "'\\''")
    return f"'{text}'"


# The order is the default order `--languages` tries them in.
LANGUAGES = {
    "python": Language(
        ["python3", "-c"],
        ".py",
        repr,
        "{entry}({args})",
        ", ",
        "import sys; print('%d.%d' % sys.version_info[:2])",
        (3, 10),
    ),
    "node": Language(
        ["node", "-e"],
        ".js",
        json.dumps,
        "{entry}({args})",
        ", ",
        "console.log(process.versions.node)",
        (20,),
    ),
    "perl": Language(
        ["perl", "-e"],
        ".pl",
        perl_literal,
        "&{entry}({args})",
        ", ",
        r'printf "%vd\n", $^V',
        (5, 34),
    ),
    "ruby": Language(
        ["ruby", "-e"],
        ".rb",
        ruby_literal,
        "{entry}({args})",
        ", ",
        r"puts RUBY_VERSION[/\A\d+\.\d+/]",
        (3, 3),
    ),
    "php": Language(
        ["php", "-r"],
        ".php",
        php_literal,
        "{entry}({args});",
        ", ",
        'echo PHP_MAJOR_VERSION, ".", PHP_MINOR_VERSION;',
        (8, 2),
    ),
    "busybox": Language(
        ["busybox", "sh", "-c"],
        ".sh",
        sh_literal,
        "{entry} {args}",
        " ",
        'v=$(busybox | head -n 1); v=${v#BusyBox v}; echo "${v%% *}"; '
        "busybox nc 2>&1 | grep -q -- '-s ADDR' || echo 'the full nc'",
        (1, 36),
    ),
}


def source(module, entry, *arguments, language="python"):
    """Return `module`'s file in `language`, then one call to `entry(*arguments)`.

    The file sits beside the module with the language's suffix, so `wire` in
    `node` is `wire.js`.
    """
    spoken = LANGUAGES[language]
    args = spoken.sep.join(map(spoken.literal, arguments))
    text = Path(module.__file__).with_suffix(spoken.suffix).read_text(encoding="utf-8")
    return f"{text}\n{spoken.call.format(entry=entry, args=args)}\n"


def exec_command(runtime, name, program, language="python", interactive=False):
    """Return the exec command that runs `program` in `language` inside container `name`.

    `interactive` adds `-i`, which keeps the program's stdin connected. The helper
    needs it for its frames and its stop. Without it, the helper never exits.
    """
    interpreter = LANGUAGES[language].interpreter
    return [*EXEC[runtime], *(["-i"] if interactive else []), name, *interpreter, program]
