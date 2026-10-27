// Ask Ollama one question from inside a container, and print the answer as it streams.
//
// The twin of query.py, for a container with node and no python3. The container
// receives this source through `node -e`, then one call to `ask`. It uses Node
// built-ins only, runs on Node 20, and prints the same failure lines as query.py.

"use strict";

const http = require("http");

const MODEL = "hf.co/CohereLabs/tiny-aya-global-GGUF:Q4_K_M";
const PROMPT = "Say hello from a container in five sentences.";

// Print one line to stderr and set exit 1, leaving Node to finish its writes.
function fail(message) {
  process.stderr.write(`hello-127: ${message}\n`);
  process.exitCode = 1;
}

// Post the prompt to address:port and print the streamed answer.
//
// The answer counts as finished only at Ollama's `done` line. A stream that ends
// before it fails, however it ends.
function ask(address, port) {
  const body = JSON.stringify({
    model: MODEL,
    messages: [{ role: "user", content: PROMPT }],
  });
  let answered = false;
  let finished = false;

  // End the run once: a newline after any answer, then the failure, if there is one.
  function finish(message, newline) {
    if (finished) return;
    finished = true;
    if (newline) process.stdout.write("\n");
    if (message !== undefined) fail(message);
  }

  // Act on one streamed line: print its part, or end on `done` or an error.
  function handle(line) {
    if (finished || !line.trim()) return;
    const part = JSON.parse(line);
    if ("error" in part) {
      finish(`Ollama stopped with an error: ${part.error}`, true);
      return;
    }
    process.stdout.write(part.message.content);
    if (part.done) finish(undefined, true);
  }

  const request = http.request(
    {
      host: address,
      port,
      path: "/api/chat",
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(body),
      },
    },
    (reply) => {
      answered = true;
      reply.setEncoding("utf8");
      if (reply.statusCode >= 400) {
        let text = "";
        reply.on("data", (chunk) => (text += chunk));
        reply.on("end", () => {
          let error = "";
          try {
            error = JSON.parse(text).error || "";
          } catch {
            // not JSON: the status alone says enough
          }
          finish(`Ollama answered ${reply.statusCode}: ${error}`);
        });
        return;
      }
      let rest = "";
      reply.on("data", (chunk) => {
        const lines = (rest + chunk).split("\n");
        rest = lines.pop();
        lines.forEach(handle);
      });
      reply.on("end", () => handle(rest));
      reply.on("error", () => {}); // a cut mid-stream; close follows
      reply.on("close", () =>
        finish("the answer was cut off before Ollama finished it", true),
      );
    },
  );
  request.on("error", (error) => {
    if (answered || finished) return;
    if (error.code === "ECONNREFUSED") {
      finish(`nothing answers on ${address}:${port} here. Is the tunnel running?`);
    } else if (error.code === "ECONNRESET") {
      finish("the tunnel closed the connection. Is Ollama running on the Mac?");
    } else {
      finish(`cannot reach ${address}:${port}: ${error.message}`);
    }
  });
  request.end(body);
}
