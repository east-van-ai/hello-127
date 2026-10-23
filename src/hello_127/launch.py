"""The exec commands that run a program from this package inside a container."""

from pathlib import Path

EXEC = {"docker": ["docker", "exec"], "container": ["container", "exec"]}


def source(module, entry, *arguments):
    """Return `module`'s own file, then one call to `entry(*arguments)`, for `python3 -c`."""
    call = ", ".join(map(repr, arguments))
    return f"{Path(module.__file__).read_text()}\n{entry}({call})\n"


def exec_command(runtime, name, program, interactive=False):
    """Return the exec command that runs `program` with python3 inside container `name`.

    `interactive` adds `-i`, which keeps the program's stdin connected. The helper
    needs it for its frames and its stop. Without it, the helper never exits.
    """
    return [*EXEC[runtime], *(["-i"] if interactive else []), name, "python3", "-c", program]
