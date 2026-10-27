// Carry TCP connections as frames over a pair of pipes: the inside half, in PHP.
//
// The twin of wire.py's inside half, for a container with php and neither python3
// nor node. The container receives this source through `php -r`, then one call to
// `listen`, so the file opens with no PHP tag. It uses core PHP only, runs on
// PHP 8.2, and never writes to stdout, which is the wire. The frame format is
// wire.py's: a change to one lands in the others.

// The CLI prints warnings to stdout unless told otherwise, and stdout is the wire.
ini_set("display_errors", "stderr");

const OPEN = 1;
const DATA = 2;
const CLOSE = 3;
const HEADER_SIZE = 9;
const CHUNK = 65536;

// Print one line to stderr, since stdout belongs to the frames.
function wire_log($message)
{
    fwrite(STDERR, "hello-127: $message\n");
}

// Return one frame: kind, connection number, payload length, then the payload.
function frame($kind, $conn, $payload = "")
{
    return pack("CNN", $kind, $conn, strlen($payload)) . $payload;
}

// Return the first whole frame in `$pending` as [kind, conn, payload, rest], or null.
function next_frame($pending)
{
    if (strlen($pending) < HEADER_SIZE) {
        return null;
    }
    $header = unpack("Ckind/Nconn/Nlength", $pending);
    $end = HEADER_SIZE + $header["length"];
    if (strlen($pending) < $end) {
        return null;
    }
    return [
        $header["kind"],
        $header["conn"],
        substr($pending, HEADER_SIZE, $header["length"]),
        substr($pending, $end),
    ];
}

// Write all of `$bytes` to `$stream`, blocking while it is full. False once it fails.
function write_all($stream, $bytes)
{
    while ($bytes !== "") {
        $written = @fwrite($stream, $bytes);
        if ($written === false || ($written === 0 && feof($stream))) {
            return false;
        }
        $bytes = substr($bytes, $written);
    }
    return true;
}

// Listen on each [address, port] in `$listeners`, and dial `$targets` on request.
//
// The helper's OPEN carries its listener's index in `$listeners`, so the Mac side
// knows where to dial. The Mac's OPEN carries an index in `$targets`, the address
// and port to dial in here. A listener that cannot bind ends the helper, with no
// partial tunnel.
//
// One stream_select loop watches stdin, the listeners, and every socket still
// reading. Writes block, so a full stdout stalls the sockets, and a full socket
// stalls stdin, as in the other wires. The dial blocks too, so no DATA frame
// overtakes its own connection's dial.
function listen($listeners, $targets)
{
    $servers = [];
    foreach ($listeners as $index => [$address, $port]) {
        $server = @stream_socket_server("tcp://$address:$port", $errno, $errstr);
        if ($server === false) {
            $reason = stripos($errstr, "in use") !== false
                ? "already in use in this container"
                : $errstr;
            wire_log("inside: cannot listen on $address:$port: $reason");
            exit(1);
        }
        $servers[$index] = $server;
        wire_log("inside: listening on $address:$port");
    }

    stream_set_blocking(STDIN, false);
    stream_set_read_buffer(STDIN, 0);
    $sockets = []; // conn -> socket
    $reading = []; // conn -> socket, while its read direction is open
    $remaining = []; // conn -> directions still open, from 2 down to 0
    $next_conn = 1; // odd inside, even on the Mac
    $pending = "";

    // Count one direction of a connection as done, and drop it once both are.
    $finish_half = function ($conn) use (&$sockets, &$remaining) {
        if (!isset($remaining[$conn])) {
            return;
        }
        $remaining[$conn] -= 1;
        if ($remaining[$conn] === 0) {
            fclose($sockets[$conn]);
            unset($sockets[$conn], $remaining[$conn]);
        }
    };

    // Send CLOSE once a socket's reading ends, however it ends.
    $read_ended = function ($conn) use (&$reading, $finish_half) {
        unset($reading[$conn]);
        write_all(STDOUT, frame(CLOSE, $conn));
        $finish_half($conn);
    };

    while (true) {
        $watch = array_merge([STDIN], array_values($servers), array_values($reading));
        $none = null;
        if (@stream_select($watch, $none, $none, null) === false) {
            continue; // a signal woke the select
        }
        foreach ($watch as $ready) {
            if ($ready === STDIN) {
                $chunk = fread(STDIN, CHUNK);
                if ($chunk === "" || $chunk === false) {
                    if (feof(STDIN)) {
                        break 2;
                    }
                    continue;
                }
                $pending .= $chunk;
                while (($got = next_frame($pending)) !== null) {
                    [$kind, $conn, $payload, $pending] = $got;
                    if ($kind === OPEN) {
                        $index = unpack("n", $payload)[1];
                        if (!isset($targets[$index])) {
                            wire_log("connection $conn: dial failed: no target number $index");
                            write_all(STDOUT, frame(CLOSE, $conn));
                            continue;
                        }
                        [$address, $port] = $targets[$index];
                        $socket = @stream_socket_client("tcp://$address:$port", $errno, $errstr);
                        if ($socket === false) {
                            wire_log("connection $conn: dial failed: $errstr");
                            write_all(STDOUT, frame(CLOSE, $conn));
                            continue;
                        }
                        stream_set_read_buffer($socket, 0);
                        $sockets[$conn] = $socket;
                        $reading[$conn] = $socket;
                        $remaining[$conn] = 2;
                        continue;
                    }
                    if (!isset($sockets[$conn])) {
                        continue;
                    }
                    if ($kind === DATA) {
                        write_all($sockets[$conn], $payload);
                    } elseif ($kind === CLOSE) {
                        @stream_socket_shutdown($sockets[$conn], STREAM_SHUT_WR);
                        $finish_half($conn);
                    }
                }
            } elseif (($index = array_search($ready, $servers, true)) !== false) {
                $socket = @stream_socket_accept($ready, 0);
                if ($socket === false) {
                    continue;
                }
                stream_set_read_buffer($socket, 0);
                $conn = $next_conn;
                $next_conn += 2;
                $sockets[$conn] = $socket;
                $reading[$conn] = $socket;
                $remaining[$conn] = 2;
                write_all(STDOUT, frame(OPEN, $conn, pack("n", $index)));
            } else {
                $conn = array_search($ready, $reading, true);
                $chunk = @fread($ready, CHUNK);
                if ($chunk === "" || $chunk === false) {
                    $read_ended($conn); // an end or a reset
                } else {
                    write_all(STDOUT, frame(DATA, $conn, $chunk));
                }
            }
        }
    }

    foreach ($sockets as $socket) {
        fclose($socket);
    }
    foreach ($servers as $server) {
        fclose($server);
    }
    wire_log("inside: input ended, helper exiting");
}
