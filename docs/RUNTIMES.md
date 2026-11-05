# Runtimes

The README walks through Docker Desktop. This covers every other runtime
hello-127 runs on: three more Docker engines, and Apple Container. The
setup is the README's: Ollama running on the Mac, with Tiny Aya pulled.

## Two runtime words

hello-127 takes one of two runtime words, and each names a command:

| Word | Command | Reaches |
| --- | --- | --- |
| `docker` | `docker` | Docker Desktop, Colima, OrbStack, Podman |
| `container` | `container` | Apple Container |

Apple Container gets its own word because it speaks its own API, through
its own command. The four Docker engines all speak the Docker API, so one
word covers them all.

## How `docker` picks an engine

The `docker` command never runs a container itself. It is a client. It
sends requests over a socket to an engine, the program that runs the
containers. A **context** names that socket.

| Context | Engine behind the socket |
| --- | --- |
| `desktop-linux` | Docker's own engine, in Docker Desktop's VM |
| `colima` | Docker's own engine, in a Lima VM |
| `orbstack` | Docker's own engine, in OrbStack's VM |
| `podman` | Podman's own engine, speaking the Docker API |

hello-127 runs `docker exec` and `docker inspect`, so it goes wherever
`docker` goes. No flag, no config. `docker version` shows which engine
answered: the client line stays the same, and the server line changes.

```bash
docker context ls
```

The current context has a `*`. It lives in one line of
`~/.docker/config.json`, `currentContext`, which every terminal on the Mac
shares.

There are two ways to pick an engine:

- **For one run**, set `DOCKER_CONTEXT`. hello-127 passes its environment
  to the `docker` it starts, so the variable reaches it. The Mac-wide
  setting stays as it was.

  ```bash
  DOCKER_CONTEXT=colima hello-127 tunnel docker h127 --out 11434:127.0.0.1:11434
  ```

- **For every terminal**, `docker context use colima`. It rewrites
  `currentContext`, and every later `docker` command follows it.

## Colima

Colima runs Docker's own engine in a [Lima](https://lima-vm.io/) VM.

```bash
brew install colima
colima start --cpu 2 --memory 2
```

`colima start` creates the `colima` context and makes it current, for
every terminal. The README's walkthrough then runs with no change. On
Colima's default network, `limactl` is the process that dials the Mac.

## OrbStack

OrbStack runs Docker's own engine in its own VM. It is free for personal
use, and paid for work.

```bash
brew install --cask orbstack
```

Its first launch creates the `orbstack` context and makes it current. The
walkthrough runs with no change. Its memory grows only as used. On its
default network, `OrbStack Helper` is the process that dials the Mac.

## Podman

Podman runs its own engine in a VM, and imitates the Docker API. Its
containers run as an ordinary user inside the VM, not as root.

```bash
brew install podman
podman machine init --cpus 2 --memory 2048
podman machine start
```

Podman makes no context. `podman machine start` prints the path of its API
socket, under the Mac's temporary folder. Create a context from it:

```bash
docker context create podman --docker host=unix://PATH
```

The socket's folder may change after a reboot. Then create the context
again from the new path.

`podman-mac-helper` is the other way in. It needs `sudo`, and points the
Mac-wide `/var/run/docker.sock` at Podman. The context needs neither.

The walkthrough runs with no change. Two things look different:

- `languages` names the image in full, as Podman spells it:
  `docker.io/library/python:3.12-slim`.
- The container's root folder has no `.dockerenv`. Podman's marker is
  `/run/.containerenv`.

`podman exec` has detach keys, ctrl-p then ctrl-q. They never cut the
tunnel: payloads full of those two bytes pass through unchanged. On
Podman's default network, `gvproxy` is the process that dials the Mac.

## Apple Container

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

## Tested with

| Runtime | Version | Engine |
| --- | --- | --- |
| Colima | 0.10.3 | Docker 29.5.2 |
| OrbStack | 2.2.5 | Docker 29.8.2 |
| Podman | 6.1.4 | Podman 6.1.4 |
| Apple Container | 1.6.0 | its own |

All on macOS 26.6.2, with the Docker 29.9.2 client and Ollama 0.33.3.

## Use of AI

Both the use of AI and its disclosure are deliberate. Code and documentation in
this project are written in collaboration with Artificial Intelligence (AI). The
division of labour: the AI explores, challenges assumptions and edge cases, and
drafts; the human initiates, drafts the designs, explores alongside the AI,
reviews every change, and decides what gets committed.

---

**East Van AI** · AI for the rest of us! · Vancouver, BC, Canada

[github.com/east-van-ai](https://github.com/east-van-ai) · <east-van-ai@proton.me>

Copyright (c) 2026 Go Nakamaru
