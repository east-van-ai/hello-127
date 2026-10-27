# Languages

The README walks through a Python image. This is the same walkthrough for
every other language the helper comes in: Node, Perl, Ruby, PHP, and
BusyBox. Each image carries one interpreter and no Python, or no interpreter
at all, and the commands stay the same. Only three things change per
language: the image, the small service started inside, and the lines that
come back.

The setup is the README's: Ollama running on the Mac, with Tiny Aya pulled.
The tests at the end of each section need a clone, like the README's unit
tests. Each one runs two ways: with the language installed on the Mac, or
in a container with the clone mounted read-only and no network, so nothing
needs installing. The container lines show Docker. On Apple Container,
`container run` takes the same flags.

## The steps

Every section below fills in steps 1 and 2. The rest is the same for every
image.

1. Start a container with no network, named `h127`.
2. Start a small web server inside it, on the container's own
   127.0.0.1:8000. It answers every request with one line naming its
   language.
3. In the first terminal, start the tunnel both ways:

   ```bash
   hello-127 tunnel docker h127 --out 11434:127.0.0.1:11434 --in 8080:127.0.0.1:8000
   ```

   ```text
   hello-127: tunnel uses node 20.20.2 in container h127
   hello-127: outside: relaying inside 127.0.0.1:11434 to 127.0.0.1:11434
   hello-127: outside: listening on 127.0.0.1:8080 for 127.0.0.1:8000 inside
   hello-127: outside: Ctrl-C to stop
   hello-127: inside: listening on 127.0.0.1:11434
   ```

   The first line names the language hello-127 picked.
4. In the second terminal, reach the service inside from the Mac:

   ```bash
   curl http://127.0.0.1:8080/
   ```

5. Ask Ollama from inside the container:

   ```bash
   hello-127 ollama-query docker h127
   ```

6. Ctrl-C the tunnel, then `docker stop h127` removes the container.

Apple Container works the same way: `container run` and `container exec`
in steps 1 and 2, and `tunnel container` and `ollama-query container` after.

## Node

```bash
docker run -d --rm --name h127 --network none node:20-slim sleep infinity
docker exec -d h127 node -e 'require("http").createServer((req, res) => res.end("hello from node\n")).listen(8000, "127.0.0.1")'
```

`curl` prints `hello from node`. The query streams Tiny Aya's answer:

```text
hello-127: ollama-query uses node 20.20.2 in container h127
Hello from the container! It's a cozy and slightly cramped space, ...
```

### Tests

The unit tests run the Node helper wherever `node` is on PATH, and skip it
otherwise. The parser has its own tests in `node:test`:

```bash
node --test tests/test_wire.js
```

Or in the Node image:

```bash
docker run --rm --network none -v "$PWD":/w:ro -w /w node:20-slim node --test tests/test_wire.js
```

```text
...
# tests 10
# pass 10
# fail 0
```

## Perl

```bash
docker run -d --rm --name h127 --network none debian:bookworm-slim sleep infinity
docker exec -d h127 perl -MIO::Socket::INET -e '$s = IO::Socket::INET->new(LocalAddr => "127.0.0.1", LocalPort => 8000, Listen => 5, ReuseAddr => 1) or die $!; while ($c = $s->accept) { while (<$c>) { last if /^\r?$/ } print $c "HTTP/1.0 200 OK\r\n\r\nhello from perl\n"; close $c }'
```

`debian:bookworm-slim` has Perl and nothing else to run a script with. Its
Perl is the cut-down one, with no JSON module, so the Perl query asks no
question. It checks that Ollama answers:

```text
hello-127: ollama-query uses perl 5.36.0 in container h127
Ollama is running
```

`curl` prints `hello from perl`.

### Tests

The unit tests run the Perl helper with a `perl` of 5.34 or newer on PATH.
The Perl in macOS is 5.34, so it counts. The parser has its own tests,
in `Test::More`, which comes with Perl:

```bash
perl tests/test_wire.pl
```

Or in a Perl image. `debian:bookworm-slim` has no `Test::More`, so the
tests take the official Perl image instead:

```bash
docker run --rm --network none -v "$PWD":/w:ro -w /w perl:5.34-slim perl tests/test_wire.pl
```

```text
ok 1 - frame writes kind, connection, and length big-endian, then the payload
...
ok 27 - the largest connection number survives the round trip
1..27
```

## Ruby

```bash
docker run -d --rm --name h127 --network none ruby:3.3-alpine sleep infinity
docker exec -d h127 ruby -rsocket -e 's = TCPServer.new("127.0.0.1", 8000); loop { c = s.accept; while (l = c.gets) && l != "\r\n"; end; c.print "HTTP/1.0 200 OK\r\n\r\nhello from ruby\n"; c.close }'
```

`curl` prints `hello from ruby`. The query streams Tiny Aya's answer:

```text
hello-127: ollama-query uses ruby 3.3 in container h127
Hello! I'm [Your AI Assistant Name], here to assist with your queries. ...
```

### Tests

The unit tests run the Ruby helper with a `ruby` of 3.3 or newer first on
PATH. macOS ships 2.6 in `/usr/bin`, so on a Mac they skip until a newer
Ruby comes first. The parser has its own tests, in Minitest, which comes
with Ruby:

```bash
ruby tests/test_wire.rb
```

Or in the Ruby image, which needs no newer Ruby on the Mac:

```bash
docker run --rm --network none -v "$PWD":/w:ro -w /w ruby:3.3-alpine ruby tests/test_wire.rb
```

```text
Run options: --seed 39900

# Running:

..........

Finished in 0.002097s, 4769.4746 runs/s, 12877.5814 assertions/s.

10 runs, 27 assertions, 0 failures, 0 errors, 0 skips
```

## PHP

```bash
docker run -d --rm --name h127 --network none php:8.2-cli sleep infinity
docker exec -d h127 php -r '$s = stream_socket_server("tcp://127.0.0.1:8000"); while ($c = stream_socket_accept($s, -1)) { while (($l = fgets($c)) !== false && $l !== "\r\n"); fwrite($c, "HTTP/1.0 200 OK\r\n\r\nhello from php\n"); fclose($c); }'
```

`php:8.2-cli` is built on Debian, so it carries Perl too, and Perl comes
first in the order. `--languages php` on both commands pins PHP:

```bash
hello-127 tunnel docker h127 --out 11434:127.0.0.1:11434 --in 8080:127.0.0.1:8000 --languages php
hello-127 ollama-query docker h127 --languages php
```

`curl` prints `hello from php`. The query streams Tiny Aya's answer:

```text
hello-127: ollama-query uses php 8.2 in container h127
Hello! From within the container, my signal lights blink green, ...
```

Without the flag, the same image runs the Perl helper and the Perl query.

### Tests

The unit tests run the PHP helper wherever `php` is on PATH, and skip it
otherwise. PHP ships no test runner, so the parser's test file carries a
small one of its own, in PHPUnit's shape:

```bash
php tests/test_wire.php
```

Or in the PHP image:

```bash
docker run --rm --network none -v "$PWD":/w:ro -w /w php:8.2-cli php tests/test_wire.php
```

```text
..........

OK (10 tests, 27 assertions)
```

## BusyBox

```bash
docker run -d --rm --name h127 --network none busybox:1.37 sleep infinity
docker exec -d h127 nc -lk -s 127.0.0.1 -p 8000 -e sh -c 'while read -r l && [ "${l%?}" ]; do :; done; printf "HTTP/1.0 200 OK\r\n\r\nhello from busybox\n"'
```

`busybox:1.37` has BusyBox and nothing else, so no interpreter at all. The
helper is a shell script, sent to `busybox sh -c`. It needs the full `nc`,
with `-s` to bind loopback only. Alpine 3.18 and newer have it, and so do
the official `busybox` images. Ubuntu's and Debian's `busybox` packages
leave it out, so there hello-127 names the version and the missing piece,
such as `busybox 1.36.1 (needs the full nc)`. BusyBox comes last
in the order, since every image with an interpreter does better.

BusyBox has no JSON, so the BusyBox query asks no question. It checks that
Ollama answers:

```text
hello-127: ollama-query uses busybox 1.37.0 in container h127
Ollama is running
```

`curl` prints `hello from busybox`.

The shell cannot close one direction of a socket. A client inside that ends
its side early still gets its answer. An `--in` client on the Mac that does
the same, then waits for the reply, waits forever. Clients that send a
request and read the reply, like `curl` here, are not affected.

### Tests

macOS has no BusyBox, so the BusyBox tests run in an Alpine image that has
Python too. The `-k` picks them out:

```bash
docker run --rm --network none -v "$PWD":/w:ro -w /w -e PYTHONPATH=src -e PYTHONDONTWRITEBYTECODE=1 python:3.14-alpine python -m unittest -k BusyBox
```

```text
Ran 20 tests in 11.880s

OK (expected failures=2)
```

The two expected failures are the `--in` cases that need that half-close.

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
