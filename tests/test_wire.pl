# Pin wire.pl's frames and parser with fixed bytes, no timing involved.
# Run with `perl tests/test_wire.pl`; Test::More ships with Perl.

use strict;
use warnings;
use FindBin;
use Test::More;

# At compile time, so the constants are known before the cases below are read. The
# file ends on a sub, not a true value, so a failed load shows in $@ and $! alone.
BEGIN {
    my $wire = "$FindBin::Bin/../src/hello_127/wire.pl";
    do $wire;
    die $@ if $@;
    die "cannot load $wire: $!" unless defined &main::frame;
}

# The cases from test_wire.js, in the same order.

is(frame(DATA, 258, "abc"), "\x02\x00\x00\x01\x02\x00\x00\x00\x03abc",
    "frame writes kind, connection, and length big-endian, then the payload");

is(frame(CLOSE, 7), "\x03\x00\x00\x00\x07\x00\x00\x00\x00",
    "a frame with no payload is the header alone");

ok(!defined next_frame(""), "next_frame waits for a whole header: nothing");
ok(!defined next_frame("\x02\x00\x00\x00\x01\x00\x00\x00"),
    "next_frame waits for a whole header: eight bytes");

{
    my $whole = frame(DATA, 1, "hello");
    ok(!defined next_frame(substr($whole, 0, -1)), "next_frame waits for a whole payload");
}

is_deeply(next_frame(frame(DATA, 9, "hi")), [DATA, 9, "hi", ""],
    "next_frame reads one frame exactly, with nothing left");

{
    my ($kind, undef, $payload, $rest) = @{ next_frame(frame(DATA, 1, "one") . frame(CLOSE, 1)) };
    is_deeply([$kind, $payload], [DATA, "one"], "two frames in one buffer: the first");
    is_deeply(next_frame($rest), [CLOSE, 1, "", ""], "two frames in one buffer: the second");
}

is_deeply(next_frame(frame(DATA, 4, "")), [DATA, 4, "", ""],
    "next_frame reads a DATA frame with an empty payload");

{
    my $whole = frame(DATA, 5, "split");
    for my $at (1 .. HEADER_SIZE - 1) {
        my $first = substr($whole, 0, $at);
        ok(!defined next_frame($first), "split at $at: waits");
        my (undef, $conn, $payload) = @{ next_frame($first . substr($whole, $at)) };
        is_deeply([$conn, $payload], [5, "split"], "split at $at: reads once both parts arrive");
    }
}

{
    my ($kind, $conn, $payload) = @{ next_frame(frame(OPEN, 3, pack("n", 513))) };
    is_deeply([$kind, $conn, unpack("n", $payload)], [OPEN, 3, 513],
        "an OPEN carries its listener's index in two bytes");
}

is(next_frame(frame(CLOSE, 2**32 - 1))->[1], 2**32 - 1,
    "the largest connection number survives the round trip");

done_testing();
