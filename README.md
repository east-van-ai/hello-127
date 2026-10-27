# hello-127 - one pipe between two loopbacks

![CI](https://github.com/east-van-ai/hello-127/actions/workflows/ci.yaml/badge.svg)

Can a container with no network still reach Ollama on the Mac's 127.0.0.1?
Yes, and it takes one command:

```bash
hello-127 tunnel docker h127 --out 11434:127.0.0.1:11434 --in 8080:127.0.0.1:8000
```

An agent works in `h127`, a container with `--network none`. It asks Ollama
on the Mac's `127.0.0.1:11434` for help, as if Ollama ran right beside it.
It serves the app it is building on its own `127.0.0.1:8000`. You open that
app at `127.0.0.1:8080` on the Mac. Swap `docker` for `container`, and the
same command runs on Apple Container.

Simple is the point:

- **Nothing to install in the image.** hello-127 sends a small helper to an
  interpreter the image already has.
- **The container keeps `--network none`.** The tunnel is a pipe: the
  standard streams of `docker exec -i` or `container exec -i`.
- **No sudo, no firewall exception.** On the Mac, hello-127 is a local
  program dialling loopback.
- **One command, in the foreground.** No daemon, no config file. Ctrl-C
  stops it.

## Install

- A Mac.
- [uv](https://docs.astral.sh/uv/), which installs hello-127 and fetches
  its Python.
- [Docker Desktop](https://www.docker.com/products/docker-desktop/), or
  [Apple Container](https://github.com/apple/container).
- hello-127, from PyPI:

  ```bash
  uv tool install hello-127
  ```

hello-127 itself needs nothing beyond Python's standard library.

## Why not the network

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

## Loopback only

Every address must be loopback, on both ends of both flags. A wider address
on the Mac would make it a relay to the LAN, out of a container with no
network or into one. A wider one inside, such as 0.0.0.0, would publish the
service to any network the container does have. hello-127 refuses both
before anything runs:

```text
usage: hello-127 tunnel RUNTIME CONTAINER (--out SPEC | --in SPEC)... [--languages LIST]
hello-127 tunnel: error: argument --out: not a loopback address: '10.0.0.5'
```

## How it works

hello-127 does the job of `com.docker.backend` on purpose, through a pipe
every runtime already has. `docker exec -i` and `container exec -i` run a
**helper** program inside a container and hand you its standard input and
output.

```text
  Mac                                          container (--network none)
 ┌────────────────────────────┐              ┌──────────────────────────────┐
 │       ┌──────────┐         │              │                 your program │
 │    ┌─►│ Ollama   │ ─┐      │              │              connects to │   │
 │    │  └──────────┘  ▼      │    stdin     │          127.0.0.1:11434 ▼   │
 │    │        hello-127  ────┼──────────────┼────────────────────►  helper │
 │    └─ 127.0.0.1:11434 ◄────┼──────────────┼◄─────────────────────────┘   │
 │                            │    stdout    │                              │
 └────────────────────────────┘              └──────────────────────────────┘
```

- **Inside the container**, a small helper listens on 127.0.0.1:11434. It
  shares the container's network, so your program sees Ollama as local.
- **On the wire**, each connection becomes frames: open, data, close, each
  tagged with a connection number. Many connections share one pipe.
- **On the Mac**, hello-127 reads the frames and dials Ollama on loopback.

None of this is new. SSH's `ProxyCommand` carries one TCP stream over a
program's standard streams. `ssh -L` and `kubectl port-forward` carry many
connections through one channel.

### The helper

The helper is never installed in the image. hello-127 sends its source as an
argument to an interpreter the image already has. It is written six times,
once per language, and all six speak the same wire as the Mac side:

| Choice | Language | Sent to | Needs | An image with it |
| --- | --- | --- | --- | --- |
| python | Python | `python3 -c` | Python 3.10 | `python:3.12-slim` |
| node | JavaScript | `node -e` | Node 20 | `node:20-slim` |
| perl | Perl | `perl -e` | Perl 5.34 | `debian:bookworm-slim` |
| ruby | Ruby | `ruby -e` | Ruby 3.3 | `ruby:3.3-alpine` |
| php | PHP | `php -r` | PHP 8.2 | `php:8.2-cli` |
| busybox | sh | `busybox sh -c` | BusyBox 1.36 | `alpine` |

hello-127 tries them in that order, and the first one present and new
enough wins. `--languages` takes names from the Choice column:
`--languages ruby,php` sets a different order, and one name tries only that
language. The Mac side never changes.

`languages` shows what a running container can use. It names the image,
then one row per choice, in that order:

```bash
hello-127 languages docker h127
```

```text
container h127 runs php:8.2-cli
python   ---
node     ---
perl     perl 5.40.1
ruby     ---
php      php 8.2
busybox  ---
```

Debian-based images carry Perl, so `php:8.2-cli` picks Perl unless
`--languages php` pins PHP. `---` marks a missing interpreter. One that is
there but cannot be used says why, such as
`busybox 1.36.1 (needs the full nc)`.

BusyBox is for an image with no interpreter at all, such as `alpine`. It
comes last, since a shell cannot close one direction of a socket.

Under load they differ. A stress test held 4000 connections at once
through Python and Node, and neither broke. They are the ones to pick.
Perl and Ruby hold thousands opened in turn, but a burst of a thousand
loses some. PHP hangs at 1021. BusyBox is the weakest by far: a burst of a
dozen loses some, and each connection costs about seven processes. Treat
it as a backup, for a job that connects now and then, like a periodic
database check.

An image with none of them stops the command with one line, before anything
is relayed:

```text
hello-127: container h127 has no interpreter tunnel can use: no python3, no node, no perl, no ruby, no php, no busybox
```

## What it is not

It carries bytes, and never reads them. Whatever the service lets a local
client do, a program in the container can do too. The tunnel opens the whole
service, not one part of it. `--in` opens the other way: every program on the
Mac reaches the server inside, not only a browser.

It also changes how a connection ends. TCP has two endings: a clean close,
and a reset when something breaks. The pipe has no frame for a reset, so
every ending arrives as a clean close. A protocol that marks its own end,
as HTTP does, still notices a cut. A protocol that simply stops at the end
of the connection cannot tell a crash from a finish.

A gatekeeper is the other design. It understands each request and decides
what to allow. hello-127 makes the pipe on purpose and leaves the deciding
out.

## How it fails

Each of these was run on both runtimes. The tunnel is left as it is.

- **One slow reader stalls everyone.** All connections share one pipe. A
  client that leaves about a megabyte unread freezes every other connection.
  When it reads again, they all finish, and nothing is lost.
- **A cut-off stream can look complete.** If the tunnel dies mid-stream,
  the client sees a clean close, not an error. Whether it notices depends on
  the protocol. Against Ollama, the stock `ollama` library raises an error,
  and Python's built-in `http.client` does not.
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
  `--in` is the same mirrored: the Mac accepts first, and with nothing
  listening inside, `curl` reads "Empty reply from server".
- **The container is killed mid-stream.** The tunnel notices, reports it,
  and exits. Nothing is left connected on the Mac.
- **A Mac address nobody answers on.** Linux answers on all of 127.x, so
  the helper can listen on 127.0.0.2 inside. macOS answers only on the
  addresses its loopback carries, by default 127.0.0.1 alone. A forward to
  127.0.0.2 on the Mac holds each connection for 76 seconds, until macOS
  gives up. The client inside then reads a closed connection, as if the
  service hung up.
- **A dead forward stalls the live ones.** The Mac finishes each dial
  before it reads the next frame, so no data can overtake its own
  connection. A dial that hangs holds up every forward. Behind a forward to
  127.0.0.2, a chat on a healthy forward waited about 75 seconds for its
  first word, then streamed in full. The helper's dials for `--in` wait the
  same way, but never hang: inside, every 127.x address answers or refuses
  at once, in about 20 ms.

Two more, in BusyBox only, since the shell cannot close one direction of a
socket:

- **An `--in` half-close never arrives.** A Mac client that ends its side,
  then waits for the reply, waits forever. The server inside never sees the
  end. The same client works through every other language.
- **Stopping can leave dead processes behind.** The helper runs a few
  processes per connection. When the container's first process never
  collects the dead, as `sleep infinity` does not, they stay listed until the
  container stops. They hold nothing open.

One more, in PHP only, since it refuses to watch more than 1024 sockets
at once:

- **Connection 1021 hangs the tunnel.** Every forward stops, and the helper
  spins at full CPU. The Mac side gives up after five seconds, but the PHP
  process lives on inside the container until it stops.

One more, read from the code and never run: Windows. `tunnel` stops before
the helper starts, since asyncio on Windows cannot catch Ctrl-C the way the
tunnel asks. Past that, Ctrl-C would reach `docker` too, which the tunnel
means to stop on its own, by closing the helper's input.

And one thing that works: a client that has never heard of hello-127. It
connects to 127.0.0.1 as usual, and the tunnel does the rest. The stock
`ollama` Python library, with its default settings, works unchanged from a
container with no network.

## Unit tests

The tests need a clone, not the PyPI install:

```bash
git clone https://github.com/east-van-ai/hello-127
cd hello-127
uv run python -m unittest
```

They need no container and no Ollama. Each helper runs as a local
process, with real sockets on both sides. Every tunnel, failure, and query
case runs once per language, against the same Mac side. A language whose
interpreter is missing, or older than its floor, is skipped. The Python
floor runs only with `python3.10` on PATH.

Each of the other languages also has tests in its own language, one
section each in the languages doc. macOS has no BusyBox, so its tests run
in an Alpine image, as that doc shows.

## Try it yourself

A container started with `--network none` streams a chat from Ollama
through hello-127. Without the tunnel, the same chat is refused. It takes
three terminals.

### Setup

The demo needs [Ollama](https://ollama.com), running, with Cohere's Tiny
Aya pulled, a 2.1 GB download:

```bash
ollama pull hf.co/CohereLabs/tiny-aya-global-GGUF:Q4_K_M
```

### Start the tunnel

In the first terminal, start a container with no network, then the tunnel
into it:

```bash
docker run -d --rm --name h127 --network none python:3.12-slim sleep infinity
hello-127 tunnel docker h127 --out 11434:127.0.0.1:11434
```

- `-d` runs the container in the background.
- `--rm` deletes the container once it stops.
- `--name h127` gives it the name the other commands use.
- `--network none` leaves it with loopback only.
- `sleep infinity` keeps it running with nothing else to do.

`--out` makes one forward, for Ollama. The tunnel has no default, so every
forward is typed. The helper listens on 11434 inside, and the Mac dials
127.0.0.1:11434:

```text
hello-127: tunnel uses python3 3.12 in container h127
hello-127: outside: relaying inside 127.0.0.1:11434 to 127.0.0.1:11434
hello-127: outside: Ctrl-C to stop
hello-127: inside: listening on 127.0.0.1:11434
```

### Chat from inside the container

In the second terminal, run `ollama-query`, hello-127's sidekick. It runs
a small Python program in the container with `docker exec`. The program
asks Cohere's Tiny Aya one fixed question at 127.0.0.1:11434 and prints
the answer as it streams. It knows nothing else about the Mac.

```bash
hello-127 ollama-query docker h127
```

```text
hello-127: ollama-query uses python3 3.12 in container h127
Containerized applications are a revolutionary way to deploy and manage software, ...
```

Run it before the tunnel is up, and the same program is refused:

```text
hello-127: ollama-query uses python3 3.12 in container h127
hello-127: nothing answers on 127.0.0.1:11434 here. Is the tunnel running?
hello-127: the query exited with code 1
```

### Who is using Ollama?

In the third terminal, while the answer streams, ask who holds Ollama's
port:

```bash
lsof -nP -iTCP:11434 -sTCP:ESTABLISHED
```

- `-n` and `-P` print addresses and ports as numbers, not names.
- `-iTCP:11434` picks TCP sockets on Ollama's port, 11434.
- `-sTCP:ESTABLISHED` keeps only live connections, in the ESTABLISHED state.

```text
COMMAND     PID   USER   FD   TYPE ... NAME
ollama      803 you       7u  IPv4 ... TCP 127.0.0.1:11434->127.0.0.1:52235 (ESTABLISHED)
python3.1 55300 you       6u  IPv4 ... TCP 127.0.0.1:52235->127.0.0.1:11434 (ESTABLISHED)
```

Ollama's only client is hello-127's Python, which `lsof` cuts to
`python3.1`. It is not `com.docker.backend`. Once the answer ends, only
Ollama's listening socket is left, so the list comes back empty.

### Reach into the container

Now the other direction. In the second terminal, start a web server inside
the container, standing in for the agent's app. It listens on the
container's own loopback, so nothing on the Mac can reach it yet:

```bash
docker exec -d h127 python3 -m http.server 8000 --bind 127.0.0.1
```

Back in the first terminal, Ctrl-C the tunnel. Start it again with the
command from the top of this page, which adds `--in`:

```bash
hello-127 tunnel docker h127 --out 11434:127.0.0.1:11434 --in 8080:127.0.0.1:8000
```

```text
hello-127: tunnel uses python3 3.12 in container h127
hello-127: outside: relaying inside 127.0.0.1:11434 to 127.0.0.1:11434
hello-127: outside: listening on 127.0.0.1:8080 for 127.0.0.1:8000 inside
hello-127: outside: Ctrl-C to stop
hello-127: inside: listening on 127.0.0.1:11434
```

Now open <http://127.0.0.1:8080/> in a browser on the Mac. The page lists
the container's root folder, and `.dockerenv` near the top gives it away.
A container with no network is serving the Mac's browser. `ollama-query`
still works through `--out` at the same time.

### Other ports, both ways

Ollama is only the specimen. The tunnel carries any TCP service on
loopback, in either direction. Each forward is one flag, in the shape
`[BIND:]PORT:HOST:HOSTPORT` that `ssh` uses. The listener comes first, then
what it dials. The Mac is where the command runs, so it is ssh's local
side:

- `--out` listens inside and dials the Mac, like `ssh -R`.
- `--in` listens on the Mac and dials inside, like `ssh -L`. It reads like
  Docker's `-p HOST:CONTAINER`, and reaches a service that `-p` cannot
  publish, since the container has no network.

Both flags repeat, and one tunnel carries them all. Leave `BIND` out, and
it is 127.0.0.1. Ctrl-C the tunnel, then run the first line in the first
terminal and the second in the second:

```bash
hello-127 tunnel docker h127 --out 127.0.0.2:80:127.0.0.1:11434
hello-127 ollama-query docker h127 --connect 127.0.0.2:80
```

Here the helper listens on 127.0.0.2:80 inside, and `--connect` points
`ollama-query` at it. Two forwards may dial the same target. Two listeners
on the same address and port would never both bind, so hello-127 refuses
them.

### Clean up

Back in the first terminal, Ctrl-C closes the helper's input, and the helper
exits:

```text
hello-127: outside: stopping, closing the helper's input
hello-127: inside: input ended, helper exiting
```

Then `docker stop h127` removes the container.

### Apple Container

Apple Container works the same way, with the same flags:

```bash
container run -d --rm --name h127 --network none python:3.12-slim sleep infinity
container exec -d h127 python3 -m http.server 8000 --bind 127.0.0.1
hello-127 tunnel container h127 --out 11434:127.0.0.1:11434 --in 8080:127.0.0.1:8000
```

The chat is `hello-127 ollama-query container h127`, and `lsof` again
names hello-127's Python. <http://127.0.0.1:8080/> shows the container's
root folder, with no firewall exception and no sudo. Then
`container stop h127` removes the container.

### Tested with

macOS 26.6.2, Docker 29.9.2, Apple Container 1.6.0, and Ollama 0.33.3.

## More documentation

- [Languages](https://github.com/east-van-ai/hello-127/blob/main/docs/LANGUAGES.md):
  trying the tunnel on Node, Perl, Ruby, PHP, and BusyBox images
- [Stress](https://github.com/east-van-ai/hello-127/blob/main/docs/STRESS.md):
  how many connections each language holds, and how each one breaks
- [Changelog](https://github.com/east-van-ai/hello-127/blob/main/CHANGELOG.md): project history and releases

## Use of AI

Code and documentation are written in collaboration with remote and local AI; design
decisions, code review, semantic and auditory review, and final judgement stay human.

---

**East Van AI** · AI for the rest of us! · Vancouver, BC, Canada

[github.com/east-van-ai](https://github.com/east-van-ai) · <east-van-ai@proton.me>

Copyright (c) 2026 Go Nakamaru
