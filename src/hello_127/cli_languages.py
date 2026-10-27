"""
        hello-127 -- Languages

https://github.com/east-van-ai/hello-127

Lists which --languages choices a running container can use. It asks each
interpreter for its version, the same way `tunnel` and `ollama-query` do
before they start, but tries every language instead of stopping at the
first that fits. Nothing else runs in the container.

RUNTIME `docker` runs the probes with `docker exec`, and `container` with
Apple Container's `container exec`.

The first line names the image the container runs, as the runtime spells
it. Then it prints one row per choice, in the default order, each with what
the container has. A choice it can use shows the interpreter and its version,
such as `perl 5.36.0`. One the container lacks shows `---`. One it has
but cannot use shows what it found and what it needs, such as
`ruby 3.1.2 (needs 3.3 or newer)` or `busybox 1.36.1 (needs the full nc)`. With no --languages, the other
commands pick the first usable row.

It exits 0 whatever the container has. A container that is not running
stops it with the runtime's own message, and no rows.
"""
import json
import subprocess

from hello_127 import errors, launch, shared

HELP = "list which languages a container can run the helper in"
USAGE = "hello-127 languages RUNTIME CONTAINER"
SLOTS = ("RUNTIME", "CONTAINER")
MISSING = "---"

INSPECT = {
    "docker": ["docker", "container", "inspect", "--format", "{{.Config.Image}}"],
    "container": ["container", "inspect"],
}


def image_of(runtime, name):
    """Return the image container `name` runs, as its runtime spells it.

    Docker prints the name as it was typed. Apple Container prints JSON, with the
    full reference under `configuration.image.reference`. A container the runtime
    cannot find raises with the runtime's own first line.
    """
    try:
        answer = subprocess.run(
            [*INSPECT[runtime], name],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        raise errors.ReadinessError(f"{runtime} is not on PATH") from None
    if answer.returncode:
        said = (answer.stderr.strip() or answer.stdout.strip()).splitlines()
        reason = said[0] if said else f"exit {answer.returncode}"
        raise errors.ReadinessError(f"{runtime}: {reason}")
    if runtime == "docker":
        return answer.stdout.strip()
    return json.loads(answer.stdout)[0]["configuration"]["image"]["reference"]


def run(runtime, name, parsed):
    """Name container `name`'s image, probe every language, then print one row each."""
    image = image_of(runtime, name)
    notes = [shared.probe(runtime, name, language)[1] for language in launch.LANGUAGES]
    print(f"container {name} runs {image}")
    width = max(map(len, launch.LANGUAGES))
    for language, note in zip(launch.LANGUAGES, notes):
        print(f"{language:<{width}}  {note or MISSING}")
