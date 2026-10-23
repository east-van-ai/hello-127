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
Apple Container's `container exec`. The container must have python3, 3.10 or
newer.

With no tunnel running, the program says nothing answers on that
address and port, and exits 1.
"""
import subprocess

from hello_127 import errors, launch, query

HELP = "ask Ollama one question from inside a container, through the tunnel"
USAGE = "hello-127 ollama-query RUNTIME CONTAINER [--connect ADDRESS:PORT]"
SLOTS = ("RUNTIME", "CONTAINER")


def run(runtime, name, parsed):
    """Run the query inside container `name`, streaming its answer to stdout."""
    program = launch.source(query, "ask", *parsed.connect)
    command = launch.exec_command(runtime, name, program)
    try:
        code = subprocess.run(command).returncode
    except FileNotFoundError:
        raise errors.ReadinessError(f"{command[0]} is not on PATH") from None
    except KeyboardInterrupt:
        raise errors.RuntimeFailure("the query was interrupted") from None
    if code:
        raise errors.RuntimeFailure(f"the query exited with code {code}")
