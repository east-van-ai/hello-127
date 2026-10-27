# Carry TCP connections as frames over a pair of pipes: the inside half, in Perl.
#
# The twin of wire.py's inside half, for a container with perl and none of python3
# or node. The container receives this source through `perl -e`, then one call to
# `&listen`: the `&` matters, since a bare `listen` is Perl's own built-in. It uses
# only what Debian's perl-base carries, runs on Perl 5.34, and never writes to
# stdout, which is the wire. The frame format is wire.py's: a change to one lands
# in the others.

use strict;
use warnings;
use Errno qw(EINTR);
use IO::Select;
use IO::Socket::INET;

use constant {
    OPEN => 1,
    DATA => 2,
    CLOSE => 3,
    HEADER_SIZE => 9,
    CHUNK => 65536,
};

# Print one line to stderr, since stdout belongs to the frames.
sub wire_log {
    my ($message) = @_;
    print STDERR "hello-127: $message\n";
}

# Return one frame: kind, connection number, payload length, then the payload.
sub frame {
    my ($kind, $conn, $payload) = @_;
    $payload = "" unless defined $payload;
    return pack("CNN", $kind, $conn, length $payload) . $payload;
}

# Return the first whole frame in `$pending` as [kind, conn, payload, rest], or undef.
sub next_frame {
    my ($pending) = @_;
    return undef if length $pending < HEADER_SIZE;
    my ($kind, $conn, $length) = unpack("CNN", $pending);
    my $end = HEADER_SIZE + $length;
    return undef if length $pending < $end;
    return [$kind, $conn, substr($pending, HEADER_SIZE, $length), substr($pending, $end)];
}

# Write all of `$bytes` to `$handle`, blocking while it is full. False once it fails.
sub write_all {
    my ($handle, $bytes) = @_;
    my $done = 0;
    while ($done < length $bytes) {
        my $written = syswrite($handle, $bytes, length($bytes) - $done, $done);
        if (!defined $written) {
            next if $! == EINTR;
            return 0;
        }
        $done += $written;
    }
    return 1;
}

# Bind each [address, port] in order, or log why one cannot and exit 1.
sub bind_all {
    my ($listeners) = @_;
    my @servers;
    for my $listener (@$listeners) {
        my ($address, $port) = @$listener;
        my $server = IO::Socket::INET->new(
            LocalAddr => $address,
            LocalPort => $port,
            Proto => "tcp",
            Listen => 128,
            ReuseAddr => 1,
        );
        if (!$server) {
            my $reason = $!{EADDRINUSE} ? "already in use in this container" : "$!";
            wire_log("inside: cannot listen on $address:$port: $reason");
            exit 1;
        }
        $server->blocking(0);
        push @servers, $server;
        wire_log("inside: listening on $address:$port");
    }
    return @servers;
}

# Dial the target at `$index` in `$targets`. Return the socket, or undef after logging why.
sub dial {
    my ($conn, $index, $targets) = @_;
    my $target = $targets->[$index];
    if (!$target) {
        wire_log("connection $conn: dial failed: no target number $index");
        return undef;
    }
    my ($address, $port) = @$target;
    my $socket = IO::Socket::INET->new(PeerAddr => $address, PeerPort => $port, Proto => "tcp");
    wire_log("connection $conn: dial failed: $!") unless $socket;
    return $socket;
}

# Listen on each [address, port] in `$listeners`, and dial `$targets` on request.
#
# The helper's OPEN carries its listener's index in `$listeners`, so the Mac side
# knows where to dial. The Mac's OPEN carries an index in `$targets`, the address and
# port to dial in here. A listener that cannot bind ends the helper, with no partial
# tunnel.
#
# One IO::Select loop watches stdin, the listeners, and every socket still reading.
# Writes block, so a full stdout stalls the sockets, and a full socket stalls stdin,
# as in the other wires. The dial blocks too, so no DATA frame overtakes its own
# connection's dial. sysread and syswrite only, so no PerlIO buffer hides bytes
# from the select.
sub listen {
    my ($listeners, $targets) = @_;
    $SIG{PIPE} = "IGNORE"; # a write to a reset socket would end the helper
    my @servers = bind_all($listeners);
    binmode STDIN;
    binmode STDOUT;
    my %sockets; # conn -> socket
    my %reading; # conn -> socket, while its read direction is open
    my %remaining; # conn -> directions still open, from 2 down to 0
    my $next_conn = 1; # odd inside, even on the Mac
    my $pending = "";

    # Count one direction of a connection as done, and drop it once both are.
    my $finish_half = sub {
        my ($conn) = @_;
        return unless exists $remaining{$conn};
        $remaining{$conn} -= 1;
        if ($remaining{$conn} == 0) {
            close(delete $sockets{$conn});
            delete $remaining{$conn};
        }
    };

    # Keep a new connection: both directions open, and its socket read.
    my $keep = sub {
        my ($conn, $socket) = @_;
        $sockets{$conn} = $socket;
        $reading{$conn} = $socket;
        $remaining{$conn} = 2;
    };

    INPUT: while (1) {
        my %server_index = map { fileno($servers[$_]) => $_ } 0 .. $#servers;
        my %reading_conn = map { fileno($reading{$_}) => $_ } keys %reading;
        my $select = IO::Select->new(\*STDIN, @servers, values %reading);
        for my $ready ($select->can_read) {
            my $fd = fileno($ready);
            if ($fd == fileno(STDIN)) {
                my $got = sysread(STDIN, my $chunk, CHUNK);
                if (!defined $got) {
                    next if $! == EINTR;
                    last INPUT;
                }
                last INPUT if $got == 0;
                $pending .= $chunk;
                while (my $whole = next_frame($pending)) {
                    my ($kind, $conn, $payload);
                    ($kind, $conn, $payload, $pending) = @$whole;
                    if ($kind == OPEN) {
                        my $socket = dial($conn, unpack("n", $payload), $targets);
                        if ($socket) {
                            $keep->($conn, $socket);
                        } else {
                            write_all(\*STDOUT, frame(CLOSE, $conn));
                        }
                        next;
                    }
                    my $socket = $sockets{$conn} or next;
                    if ($kind == DATA) {
                        write_all($socket, $payload);
                    } elsif ($kind == CLOSE) {
                        shutdown($socket, 1);
                        $finish_half->($conn);
                    }
                }
            } elsif (exists $server_index{$fd}) {
                my $socket = $ready->accept or next; # the client left before the accept
                $socket->blocking(1); # macOS hands the listener's O_NONBLOCK down
                my $conn = $next_conn;
                $next_conn += 2;
                $keep->($conn, $socket);
                write_all(\*STDOUT, frame(OPEN, $conn, pack("n", $server_index{$fd})));
            } else {
                my $conn = $reading_conn{$fd};
                my $got = sysread($ready, my $chunk, CHUNK);
                next if !defined $got && $! == EINTR;
                if ($got) {
                    write_all(\*STDOUT, frame(DATA, $conn, $chunk));
                } else {
                    # an end or a reset
                    delete $reading{$conn};
                    write_all(\*STDOUT, frame(CLOSE, $conn));
                    $finish_half->($conn);
                }
            }
        }
    }

    close($_) for values %sockets;
    close($_) for @servers;
    wire_log("inside: input ended, helper exiting");
}
