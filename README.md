# hello-127

![CI](https://github.com/east-van-ai/hello-127/actions/workflows/ci.yaml/badge.svg)

Can a container with no network at all still reach a service on the Mac's
127.0.0.1, such as Ollama? Yes, through a pipe. This small experiment builds
the pipe, then records how it fails.

## How a container reaches loopback today

A program on a Mac binds to 127.0.0.1 to stay private. Ollama on a Mac does
this by default. Only programs on the same machine should reach it.

Docker Desktop bends that. When a Docker container connects to the Mac, Docker
Desktop's own process, `com.docker.backend`, opens a fresh connection to
127.0.0.1 on the Mac. Ollama sees a local client. The macOS firewall sees an
outgoing connection, and never asks.

Measured on macOS with Docker Desktop 4.92.0 and Ollama 0.33.3:

- During a run, `lsof` shows `com.docker.backend` as Ollama's only client.
- A test web server bound to 127.0.0.1 refused the Mac's own LAN address.
  A container on Docker's default network read from it anyway.

That is a gap. "Bound to loopback" stops meaning "local programs only" the
moment Docker Desktop is running.

Apple Container has no such hop. Its traffic arrives over a network
interface, so reaching Ollama there needs a firewall exception or sudo.

## The same job, on purpose

Every container runtime can already run a program inside a container and
hand you its standard input and output: `docker exec -i`, or
`container exec -i`. That is a pipe. hello-127 carries TCP through it.

```text
  container (--network none)                  Mac
 ┌──────────────────────────────┐         ┌──────────────────────────┐
 │ your program                 │         │       ┌──────────┐       │
 │   │ connects to              │         │    ┌─ │ Ollama   │◄─┐    │
 │   ▼ 127.0.0.1:11434          │  stdin  │    ▼  └──────────┘  │    │
 │ helper     ◄─────────────────┼─────────┼──  hello-127        │    │
 │   └─────────────────────────►┼─────────┼──► dials 127.0.0.1 ─┘    │
 │                              │  stdout │                          │
 └──────────────────────────────┘         └──────────────────────────┘
```

- **Inside the container**, a small helper listens on 127.0.0.1:11434. It
  shares the container's network, so your program sees Ollama as local.
- **Over the pipe**, each connection becomes frames: open, data, close, each
  tagged with a connection number. Many connections share one pipe.
- **On the Mac**, hello-127 reads the frames and dials Ollama on loopback.
  Every connection goes out, none comes in. No firewall prompt, no sudo.

The helper is not installed in the image. hello-127 sends its source as an
argument to `python3 -c`, so the image needs only `python3`, 3.10 or newer.

None of this is new. SSH's `ProxyCommand` carries one TCP stream over a
program's standard streams. `ssh -L` and `kubectl port-forward` carry many
connections through one channel.

## What it is not

It carries bytes. It never reads a request, so it forwards Ollama's whole
API. A program in the container can chat, but it can also pull or delete
models.

It also changes how a connection ends. TCP has two endings: a clean close,
and a reset when something breaks. The pipe has no frame for a reset, so
every ending arrives as a clean close. A protocol that marks its own end,
as HTTP does, still notices a cut. A protocol that simply stops at the end
of the connection cannot tell a crash from a finish.

A gatekeeper is the other design. It understands each request and decides
what to allow. hello-127 makes the pipe on purpose and leaves the deciding
out.

## What you need

- A Mac.
- [uv](https://docs.astral.sh/uv/), which runs hello-127 and fetches its
  Python.
- [Docker Desktop](https://www.docker.com/products/docker-desktop/), or
  [Apple Container](https://github.com/apple/container).
- [Ollama](https://ollama.com), running, with Cohere's Tiny Aya pulled:

  ```bash
  ollama pull hf.co/CohereLabs/tiny-aya-global-GGUF:Q4_K_M
  ```

- This repo:

  ```bash
  git clone https://github.com/east-van-ai/hello-127.git
  cd hello-127
  ```

hello-127 itself needs nothing beyond Python's standard library.

## The experiment

The test: a container started with `--network none` streams a chat from
Ollama through hello-127. Without the tunnel, the same chat is refused.

It takes three terminals. In the first, start a container with no network,
then the tunnel into it:

```bash
docker run -d --rm --name h127 --network none python:3.12-slim sleep infinity
uv run hello-127 tunnel docker h127
```

- `-d` runs the container in the background.
- `--rm` deletes the container once it stops.
- `--name h127` gives it the name the other commands use.
- `--network none` leaves it with loopback only.
- `sleep infinity` keeps it running with nothing else to do.

```text
hello-127: outside: relaying 127.0.0.1:11434 to 127.0.0.1:11434
hello-127: outside: Ctrl-C to stop
hello-127: inside: listening on 127.0.0.1:11434
```

In the second, chat from inside the container:

```bash
uv run hello-127 ollama-query docker h127
```

```text
Containerized applications are a revolutionary way to deploy and manage software, ...
```

`ollama-query` runs a small Python program in the container with
`docker exec`. It asks Cohere's Tiny Aya one fixed question at
127.0.0.1:11434 and prints the answer as it streams. It knows nothing else
about the Mac.

Run it before the tunnel is up, and the same program is refused:

```text
hello-127: nothing answers on 127.0.0.1:11434 here. Is the tunnel running?
hello-127: the query exited with code 1
```

In the third, while the answer streams, ask who holds Ollama's port:

```bash
lsof -nP -iTCP:11434 -sTCP:ESTABLISHED
```

- `-n` and `-P` print addresses and ports as numbers, not names.
- `-iTCP:11434` picks TCP sockets on Ollama's port, 11434.
- `-sTCP:ESTABLISHED` keeps only live connections, in the ESTABLISHED state.

Once the answer ends, only Ollama's listening socket is left, so the list
comes back empty.

```text
COMMAND     PID   USER   FD   TYPE ... NAME
ollama      803 you       7u  IPv4 ... TCP 127.0.0.1:11434->127.0.0.1:52235 (ESTABLISHED)
python3.1 55300 you       6u  IPv4 ... TCP 127.0.0.1:52235->127.0.0.1:11434 (ESTABLISHED)
```

Ollama's only client is hello-127's Python, which `lsof` cuts to
`python3.1`. It is not `com.docker.backend`.

Back in the first terminal, Ctrl-C closes the helper's input, and the helper
exits:

```text
hello-127: outside: stopping, closing the helper's input
hello-127: inside: input ended, helper exiting
```

Then `docker stop h127` removes the container.

Apple Container runs the same experiment, with the same flags:

```bash
container run -d --rm --name h127 --network none python:3.14-slim sleep infinity
uv run hello-127 tunnel container h127
```

The chat is `uv run hello-127 ollama-query container h127`, and `lsof`
again names hello-127's Python. Then
`container stop h127` removes the container.

Measured on macOS with Docker 29.8.0, Apple Container 1.6.0, and Ollama
0.33.3.

## Other ports

Ollama is only the specimen. The tunnel carries any TCP service on the
Mac's loopback. `--forward` picks both ends, in the shape `ssh -L` uses:

```bash
uv run hello-127 tunnel docker h127 --forward 127.0.0.2:80:127.0.0.1:11434
uv run hello-127 ollama-query docker h127 --connect 127.0.0.2:80
```

- `127.0.0.2:80` is where the helper listens inside. Leave the address out,
  and it is 127.0.0.1.
- `127.0.0.1:11434` is what the Mac dials.
- `--connect` points `ollama-query` at the helper.

`--forward` repeats, and one helper carries every listener:

```bash
uv run hello-127 tunnel docker h127 --forward 11434:127.0.0.1:11434 --forward 8080:127.0.0.1:8000
```

Two forwards may dial the same target. Two listeners on the same address
and port would never both bind, so hello-127 refuses them.

Every address must be loopback, on both ends. A wider address on the Mac
would make it a relay to the LAN for a container with no network. A wider
one inside, such as 0.0.0.0, would publish the Mac's service to any
network the container does have. hello-127 refuses both before anything
runs:

```text
usage: hello-127 tunnel RUNTIME CONTAINER [--forward SPEC]...
hello-127 tunnel: error: argument --forward: not a loopback address: '10.0.0.5'
```

## How it fails

Each of these was run on both runtimes. The tunnel is left as it is.

- **One slow reader stalls everyone.** All connections share one pipe. A
  client that leaves about a megabyte unread freezes every other connection.
  When it reads again, they all finish, and nothing is lost.
- **A cut-off stream can look complete.** If the tunnel dies mid-stream,
  the client sees a clean close, not an error. Whether it notices depends on
  the protocol. Against Ollama, the stock `ollama` library raises an error,
  and Python's built-in `http.client` does not. So `ollama-query` also
  waits for Ollama's own `done` line.
- **A crash on the Mac reads as a finish.** A test server sent 64 KiB, then
  reset the connection. A client that reads until the end got an error on
  the Mac itself. Through the tunnel, it got 64 KiB and a clean end: a
  short file that looks complete. Docker's default network does the same,
  so `com.docker.backend` hides the reset too.
- **A service that is down looks like one that hung up.** The helper
  accepts a connection before the Mac dials. With nothing listening on the
  Mac, Python's `smtplib` is refused on the Mac and on Docker's default
  network. Through the tunnel, it connects, then reads "Connection
  unexpectedly closed". With the server up, its greeting arrives as usual.
- **No `python3` in the image.** The tunnel stops at once. Apple Container
  says why. Docker prints its reason on the exec's output, which is the
  pipe, so hello-127 swallows it and shows only "code 127".
- **The container is killed mid-stream.** The tunnel notices, reports it,
  and exits. Nothing is left connected on the Mac.
- **A Mac address nobody answers on.** Linux answers on all of 127.x, so
  the helper can listen on 127.0.0.2 inside. macOS answers only on the
  addresses its loopback carries, by default 127.0.0.1 alone. A forward to
  127.0.0.2 on the Mac holds each connection for 76 seconds, until macOS
  gives up. `ollama-query` then blames Ollama: "the tunnel closed the
  connection".
- **A dead forward stalls the live ones.** The Mac finishes each dial
  before it reads the next frame, so no data can overtake its own
  connection. A dial that hangs holds up every forward. Behind a forward to
  127.0.0.2, a chat on a healthy forward waited about 75 seconds for its
  first word, then streamed in full.

And one thing that works: a client that has never heard of hello-127. It
connects to 127.0.0.1 as usual, and the tunnel does the rest. The stock
`ollama` Python library, with its default settings, works unchanged from a
container with no network.

## More documentation

- [Changelog](CHANGELOG.md): project history and releases

## Use of AI

Code and documentation are written in collaboration with remote and local AI; design
decisions, code review, semantic and auditory review, and final judgement stay human.

---

**East Van AI** · AI for the rest of us! · Vancouver, BC, Canada

[github.com/east-van-ai](https://github.com/east-van-ai) · <east-van-ai@proton.me>

Copyright (c) 2026 Go Nakamaru
