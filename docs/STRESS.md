# Stress

How many connections the tunnel holds at once, per helper language, and
how each one breaks. The short answer: pick Python or Node when you can.

| Choice | All at once | One after another | Where it breaks |
| --- | --- | --- | --- |
| python | 4000 held | not needed | did not break |
| node | 4000 held | not needed | did not break |
| perl | 500 held, 1000 some reset | 4000 held | its listen queue |
| ruby | 500 held, 1000 some reset | 4000 held | its listen queue |
| php | 500 held, 1000 some reset | 1020 held, 1021 hangs | `select()`'s ceiling |
| busybox | 10 held, 12 some reset | 300 held, slowly | `nc`'s accept queue |

"All at once" opens every connection in one burst. "One after another"
opens them in turn, then holds them all. Either way, each connection sends
a short message, ends its side, and must get the same bytes back.

## How it was measured

Each run used a fresh container with no network, capped at 1 GB of memory
and a few thousand processes. One Alpine image carried every interpreter:
Node 24, Perl 5.42, Ruby 3.4, PHP 8.5, and BusyBox 1.37, newer than the
floors in the README. A Python client inside opened the connections, and
an echo server answered on the far side. The count went up in steps, and
the run stopped at the first step that failed. The PHP ceiling was checked
again on the real tunnel, from a Mac, through `docker exec`.

## Python and Node

Neither broke. Both held 4000 connections opened in one burst, in about two
seconds.

## Perl and Ruby

Both held 4000 connections opened one after another. A burst of 1000
reset some of them: the burst overflows the queue of connections waiting
to be accepted. The connections that got through worked, and the tunnel
carried on.

## PHP

PHP held 1020 connections and hung at 1021. The helper holds one socket per
connection, beside its standard streams and its listener. At 1021, the
next socket gets descriptor number 1024. That is the most `select()` can
watch, and PHP refuses to go past it. From then on, every wait for data
fails at once. The helper retries forever, at full CPU.

That one connection takes down the whole tunnel. Every forward stops. The
helper never reads its input again, so it misses the stop. The Mac side
gives up after five seconds and ends `docker exec`, but the PHP process
lives on inside the container, still spinning, until the container stops.

A burst of 1000 reset some connections, the same as Perl and Ruby.

## BusyBox

BusyBox `nc` keeps a very short queue of connections waiting to be
accepted. A burst of a dozen reset some of them. The same burst against a
bare `nc`, with no tunnel at all, fails the same way. The limit is the
tool, not the tunnel.

Opened one after another, 300 connections held. Each one costs about
seven processes, so 300 needed about 2000. Speed suffers too. Through the
real tunnel, opening 100 connections in a row took about 17 seconds.
Python took 0.03.

So BusyBox is a backup. It suits a client that connects now and then, one
connection at a time, like a job that checks a database every few minutes.
It does not suit anything busy.

## In the unit tests

The unit tests hold a hundred connections at once through every helper,
three rounds in a row. BusyBox opens its hundred one after another, in a
single round. The tests stop there, well short of any ceiling above.

```bash
uv run python -m unittest tests.test_stress
```

```text
Ran 6 tests in 3.752s

OK (skipped=2)
```

The skips are the helpers whose interpreter is not on PATH.

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
