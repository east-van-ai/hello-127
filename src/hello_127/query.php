// Ask Ollama one question from inside a container, and print the answer as it streams.
//
// The twin of query.py, for a container with php and neither python3 nor node. The
// container receives this source through `php -r`, then one call to `ask`, so the
// file opens with no PHP tag. It uses core PHP only, runs on PHP 8.2, and prints the
// same failure lines as query.py.

// The CLI prints warnings to stdout unless told otherwise, and stdout is the answer.
ini_set("display_errors", "stderr");

const MODEL = "hf.co/CohereLabs/tiny-aya-global-GGUF:Q4_K_M";
const PROMPT = "Say hello from a container in five sentences.";

// Print one line to stderr and exit 1.
function fail($message)
{
    fwrite(STDERR, "hello-127: $message\n");
    exit(1);
}

// Post the prompt to address:port and print the streamed answer.
//
// The request is HTTP/1.0, so the answer comes unchunked and ends when the
// connection closes. The answer counts as finished only at Ollama's `done` line.
// A stream that ends before it fails, however it ends.
function ask($address, $port)
{
    $socket = @stream_socket_client("tcp://$address:$port", $errno, $errstr);
    if ($socket === false) {
        if ($errstr === "Connection refused") {
            fail("nothing answers on $address:$port here. Is the tunnel running?");
        }
        fail("cannot reach $address:$port: $errstr");
    }
    // A model loading for minutes is not a cut.
    stream_set_timeout($socket, 86400);
    $body = json_encode([
        "model" => MODEL,
        "messages" => [["role" => "user", "content" => PROMPT]],
    ]);
    @fwrite(
        $socket,
        "POST /api/chat HTTP/1.0\r\n"
        . "Host: $address:$port\r\n"
        . "Content-Type: application/json\r\n"
        . "Content-Length: " . strlen($body) . "\r\n\r\n"
        . $body
    );

    $status = @fgets($socket);
    if ($status === false || !preg_match('#^HTTP/\S+ (\d{3})#', $status, $match)) {
        fail("the tunnel closed the connection. Is Ollama running on the Mac?");
    }
    while (($line = @fgets($socket)) !== false && rtrim($line, "\r\n") !== "") {
        // headers: the body's framing is the connection's end
    }
    $code = (int) $match[1];
    if ($code >= 400) {
        $reply = json_decode((string) stream_get_contents($socket), true);
        $error = is_array($reply) ? ($reply["error"] ?? "") : "";
        fail("Ollama answered $code: $error");
    }

    while (($line = @fgets($socket)) !== false) {
        if (trim($line) === "") {
            continue;
        }
        $part = json_decode($line, true);
        if (isset($part["error"])) {
            echo "\n";
            fail("Ollama stopped with an error: {$part["error"]}");
        }
        echo $part["message"]["content"];
        fflush(STDOUT);
        if (!empty($part["done"])) {
            echo "\n";
            return;
        }
    }
    echo "\n";
    fail("the answer was cut off before Ollama finished it");
}
