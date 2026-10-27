"""
        hello-127 -- Ollama Query

https://github.com/east-van-ai/hello-127

Asks Ollama one question from inside a running container, and prints the
answer as it streams. The program runs in the container and dials
127.0.0.1:11434, or the loopback ADDRESS:PORT given to --connect, so it
reaches Ollama only through a running `tunnel` listening there.

The model is Cohere's Tiny Aya, hf.co/CohereLabs/tiny-aya-global-GGUF:Q4_K_M,
and the prompt is fixed. It is a probe, not a client.

RUNTIME `docker` runs the program with `docker exec`, and `container` with
Apple Container's `container exec`.

--languages lists the languages to try for the program, in order, the same
way `tunnel` does. `python` needs python3, 3.10 or newer, in the container.
`node` needs node, 20 or newer, `perl` needs perl, 5.34 or newer,
`ruby` needs ruby, 3.3 or newer, `php` needs php, 8.2 or newer, and
`busybox` needs busybox, 1.36 or newer, with the full nc. The first one the
container has wins, and one line on stderr names it. With none left, the
query stops with one line saying what each language found.

Four of them ask the same question and print the same lines. Perl's
standard library in a slim image has no JSON, and BusyBox has none at all,
so those two programs only ask Ollama whether it is up, and print
`Ollama is running`.

With no tunnel running, the program says nothing answers on that
address and port, and exits 1.
"""
import subprocess

from hello_127 import errors, launch, query, shared

HELP = "ask Ollama one question from inside a container, through the tunnel"
USAGE = (
    "hello-127 ollama-query RUNTIME CONTAINER [--connect ADDRESS:PORT] [--languages LIST]"
)
SLOTS = ("RUNTIME", "CONTAINER")


def run(runtime, name, parsed):
    """Run the query inside container `name`, streaming its answer to stdout."""
    language = shared.pick_language(runtime, name, parsed.languages, "ollama-query")
    program = launch.source(query, "ask", *parsed.connect, language=language)
    command = launch.exec_command(runtime, name, program, language=language)
    try:
        code = subprocess.run(command).returncode
    except FileNotFoundError:
        raise errors.ReadinessError(f"{command[0]} is not on PATH") from None
    except KeyboardInterrupt:
        raise errors.RuntimeFailure("the query was interrupted") from None
    if code:
        raise errors.RuntimeFailure(f"the query exited with code {code}")
