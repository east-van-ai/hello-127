# Check from inside a container that Ollama answers, and print what it says.
#
# A lesser twin of query.py, for a container with perl and none of python3 or node.
# Debian's perl-base carries no JSON module, so there is no chat to post or read:
# the probe asks for `/`, and Ollama answers `Ollama is running`. The container
# receives this source through `perl -e`, then one call to `&ask`. It runs on
# Perl 5.34, and prints the same connection failure lines as query.py.

use strict;
use warnings;
use Errno qw(ECONNREFUSED);
use IO::Socket::INET;

# Print one line to stderr and exit 1.
sub give_up {
    my ($message) = @_;
    print STDERR "hello-127: $message\n";
    exit 1;
}

# Ask address:port for `/` and print the body.
#
# The request is HTTP/1.0, so the body comes unchunked and ends when the
# connection closes.
sub ask {
    my ($address, $port) = @_;
    $SIG{PIPE} = "IGNORE"; # a tunnel that closes early is a line below, not a death
    my $socket = IO::Socket::INET->new(PeerAddr => $address, PeerPort => $port, Proto => "tcp");
    if (!$socket) {
        give_up("nothing answers on $address:$port here. Is the tunnel running?")
            if $! == ECONNREFUSED;
        give_up("cannot reach $address:$port: $!");
    }
    binmode $socket;
    print {$socket} "GET / HTTP/1.0\r\nHost: $address:$port\r\n\r\n";
    $socket->flush;
    my $status = <$socket>;
    my ($code) = defined $status ? $status =~ m{\AHTTP/\S+ (\d{3})} : ();
    give_up("the tunnel closed the connection. Is Ollama running on the Mac?")
        unless defined $code;
    while (defined(my $line = <$socket>)) {
        last if $line =~ /\A\r?\n\z/; # headers: the body's framing is the connection's end
    }
    give_up("Ollama answered $code") if $code >= 400;
    my $body = do { local $/; <$socket> };
    $body = "" unless defined $body;
    $body =~ s/\s+\z//;
    print "$body\n";
}
