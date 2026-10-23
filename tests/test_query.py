"""Run the query program locally against a fake Ollama, and against nothing."""

import json
import shutil
import socket
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from hello_127 import launch, query

PYTHON_FLOOR = shutil.which("python3.10")


class FakeOllama(BaseHTTPRequestHandler):
    """Answer /api/chat the way Ollama streams: one JSON object per line."""

    ending = [{"message": {"content": ""}, "done": True}]

    def do_POST(self):
        """Stream three parts of an answer and `ending`, or a 404 for a missing model."""
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if request["model"] != "hf.co/CohereLabs/tiny-aya-global-GGUF:Q4_K_M":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "model not found"}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        parts = [{"message": {"content": p}} for p in ("Hello ", "from ", "the fake.")]
        for part in parts + self.ending:
            self.wfile.write((json.dumps(part) + "\n").encode())

    def log_message(self, *args):
        """Keep the test output quiet."""


def free_port():
    """Return a TCP port on 127.0.0.1 that nothing is listening on right now."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def run_query(port, python=sys.executable):
    """Run the query program against 127.0.0.1:port and return the finished process."""
    return subprocess.run(
        [python, "-c", launch.source(query, "ask", "127.0.0.1", port)],
        capture_output=True,
        timeout=10,
    )


class QueryTest(unittest.TestCase):
    """The program that runs inside the container, run here instead."""

    def serve(self, handler):
        """Serve `handler` on a free port in a thread, and return the port."""
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def test_streams_the_answer(self):
        """The parts print in order, then a newline, exit 0."""
        query = run_query(self.serve(FakeOllama))
        self.assertEqual(query.returncode, 0)
        self.assertEqual(query.stdout, b"Hello from the fake.\n")

    def test_cut_off_answer(self):
        """A stream that ends before `done` prints what came, then fails, exit 1."""

        class CutOff(FakeOllama):
            """A fake Ollama whose answer stops before the last line."""

            ending = []

        query = run_query(self.serve(CutOff))
        self.assertEqual(query.returncode, 1)
        self.assertEqual(query.stdout, b"Hello from the fake.\n")
        self.assertEqual(
            query.stderr.decode(),
            "hello-127: the answer was cut off before Ollama finished it\n",
        )

    def test_error_mid_answer(self):
        """An error line in the stream comes through in one line, exit 1."""

        class Failing(FakeOllama):
            """A fake Ollama that fails partway through its answer."""

            ending = [{"error": "model runner has unexpectedly stopped"}]

        query = run_query(self.serve(Failing))
        self.assertEqual(query.returncode, 1)
        self.assertEqual(query.stdout, b"Hello from the fake.\n")
        self.assertEqual(
            query.stderr.decode(),
            "hello-127: Ollama stopped with an error: "
            "model runner has unexpectedly stopped\n",
        )

    def test_nothing_listening(self):
        """No tunnel: one line that says so, exit 1, no traceback."""
        port = free_port()
        query = run_query(port)
        self.assertEqual(query.returncode, 1)
        self.assertEqual(
            query.stderr.decode(),
            f"hello-127: nothing answers on 127.0.0.1:{port} here. "
            "Is the tunnel running?\n",
        )

    def test_connection_closed_without_answer(self):
        """A tunnel whose dial failed closes the connection: one line, exit 1."""
        with socket.socket() as closer:
            closer.bind(("127.0.0.1", 0))
            closer.listen()
            port = closer.getsockname()[1]

            def accept_and_close():
                """Take one connection, read the request, and close it unanswered."""
                connection, _ = closer.accept()
                connection.recv(65536)
                connection.close()

            threading.Thread(target=accept_and_close, daemon=True).start()
            query = run_query(port)
        self.assertEqual(query.returncode, 1)
        self.assertEqual(
            query.stderr.decode(),
            "hello-127: the tunnel closed the connection. "
            "Is Ollama running on the Mac?\n",
        )

    def test_model_missing(self):
        """Ollama's own error comes through in one line."""

        class NoModels(FakeOllama):
            """A fake Ollama with no models pulled."""

            def do_POST(self):
                """Answer every chat with Ollama's 404."""
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"error": "model \\"hf.co/CohereLabs/tiny-aya-global-GGUF:Q4_K_M\\" not found"}')

        query = run_query(self.serve(NoModels))
        self.assertEqual(query.returncode, 1)
        self.assertEqual(
            query.stderr.decode(),
            'hello-127: Ollama answered 404: model "hf.co/CohereLabs/tiny-aya-global-GGUF:Q4_K_M" not found\n',
        )

    @unittest.skipUnless(PYTHON_FLOOR, "python3.10 not on PATH")
    def test_on_python_floor(self):
        """The program runs on the oldest Python a container may have."""
        query = run_query(self.serve(FakeOllama), python=PYTHON_FLOOR)
        self.assertEqual(query.stdout, b"Hello from the fake.\n")


if __name__ == "__main__":
    unittest.main()
