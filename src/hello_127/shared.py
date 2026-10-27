"""What both commands use: picking the language the container can run."""

import subprocess
import sys

from hello_127 import errors, launch


def version_of(text):
    """Return `text` as a version tuple, such as (3, 12), or None if it is not one."""
    parts = text.strip().split(".")
    if not all(part.isascii() and part.isdigit() for part in parts):
        return None
    return tuple(map(int, parts))


def probe(runtime, name, language_name):
    """Ask the container's interpreter for its version. Return (fits, note).

    `fits` is true for an interpreter at or past its floor that needs nothing more,
    with a note such as `ruby 3.3`. Otherwise the note says why not:
    `node 18.19.0 (needs 20 or newer)`, or `busybox 1.36.1 (needs the full nc)`.
    A missing interpreter has no note, and the caller words it.

    The probe prints the version first. Each further line is one more need.

    A missing interpreter is exit 127 on Docker, and only a stderr line on Apple
    Container. Any other failure, such as a container that is not running, raises
    with the runtime's own first line.
    """
    language = launch.LANGUAGES[language_name]
    interpreter = language.interpreter[0]
    command = launch.exec_command(runtime, name, language.probe, language=language_name)
    try:
        answer = subprocess.run(
            command, capture_output=True, encoding="utf-8", errors="replace"
        )
    except FileNotFoundError:
        raise errors.ReadinessError(f"{runtime} is not on PATH") from None
    lines = [line.strip() for line in answer.stdout.splitlines() if line.strip()]
    version = version_of(lines[0]) if answer.returncode == 0 and lines else None
    if version is not None:
        found = f"{interpreter} {lines[0]}"
        needs = lines[1:]
        if version < language.floor:
            needs.insert(0, f"{'.'.join(map(str, language.floor))} or newer")
        if needs:
            return False, f"{found} (needs {' and '.join(needs)})"
        return True, found
    if answer.returncode == 127 or f"target executable {interpreter}" in answer.stderr:
        return False, None
    said = (answer.stderr.strip() or answer.stdout.strip()).splitlines()
    reason = said[0] if said else f"exit {answer.returncode}"
    raise errors.ReadinessError(f"{runtime}: {reason}")


def pick_language(runtime, name, languages, command_word):
    """Return the first of `languages` the container can run, and name it on stderr.

    `command_word` is the command the lines name, such as `tunnel`. With no language
    left, the refusal lists what each one found, in the order tried.
    """
    notes = []
    for language_name in languages:
        fits, note = probe(runtime, name, language_name)
        if fits:
            print(
                f"hello-127: {command_word} uses {note} in container {name}",
                file=sys.stderr,
            )
            return language_name
        notes.append(note or f"no {launch.LANGUAGES[language_name].interpreter[0]}")
    raise errors.ReadinessError(
        f"container {name} has no interpreter {command_word} can use: {', '.join(notes)}"
    )
