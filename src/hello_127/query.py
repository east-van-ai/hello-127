"""Ask Ollama one question from inside a container, and print the answer as it streams.

Sent into the container as `python3 -c`, like the helper, so it stays standard library
only and runs on Python 3.10. It dials only the address it is given.
"""

import http.client
import json
import sys
import urllib.error
import urllib.request

MODEL = "hf.co/CohereLabs/tiny-aya-global-GGUF:Q4_K_M"
PROMPT = "Say hello from a container in five sentences."


def fail(message):
    """Print one line to stderr and exit 1."""
    print(f"hello-127: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def ask(address, port):
    """Post the prompt to address:port and print the streamed answer.

    The answer counts as finished only at Ollama's `done` line. A stream that ends
    before it fails, since `http.client` ends quietly when a cut falls between chunks.
    """
    url = f"http://{address}:{port}/api/chat"
    body = json.dumps(
        {"model": MODEL, "messages": [{"role": "user", "content": PROMPT}]}
    ).encode()
    try:
        reply = urllib.request.urlopen(url, body)
    except urllib.error.HTTPError as error:
        fail(f"Ollama answered {error.code}: {json.load(error).get('error', '')}")
    except urllib.error.URLError as error:
        if isinstance(error.reason, ConnectionRefusedError):
            fail(f"nothing answers on {address}:{port} here. Is the tunnel running?")
        fail(f"cannot reach {address}:{port}: {error.reason}")
    except http.client.RemoteDisconnected:
        fail("the tunnel closed the connection. Is Ollama running on the Mac?")
    with reply:
        try:
            for line in reply:
                part = json.loads(line)
                if "error" in part:
                    print()
                    fail(f"Ollama stopped with an error: {part['error']}")
                print(part["message"]["content"], end="", flush=True)
                if part.get("done"):
                    print()
                    return
        except http.client.IncompleteRead:
            pass
    print()
    fail("the answer was cut off before Ollama finished it")
