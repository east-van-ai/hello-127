# Ask Ollama one question from inside a container, and print the answer as it streams.
#
# The twin of query.py, for a container with ruby and none of python3, node, or php.
# The container receives this source through `ruby -e`, then one call to `ask`. It
# uses the standard library only, runs on Ruby 3.3, and prints the same failure lines
# as query.py.

require "json"
require "socket"

MODEL = "hf.co/CohereLabs/tiny-aya-global-GGUF:Q4_K_M"
PROMPT = "Say hello from a container in five sentences."

# Print one line to stderr and exit 1. Not `fail`, which is Ruby's `raise`.
def give_up(message)
  abort("hello-127: #{message}")
end

# Post the prompt to address:port and print the streamed answer.
#
# The request is HTTP/1.0, so the answer comes unchunked and ends when the
# connection closes. The answer counts as finished only at Ollama's `done` line.
# A stream that ends before it fails, however it ends.
def ask(address, port)
  begin
    socket = TCPSocket.new(address, port)
  rescue Errno::ECONNREFUSED
    give_up("nothing answers on #{address}:#{port} here. Is the tunnel running?")
  rescue SystemCallError => error
    give_up("cannot reach #{address}:#{port}: #{error.message.split(" - ").first}")
  end
  body = JSON.generate(
    "model" => MODEL,
    "messages" => [{ "role" => "user", "content" => PROMPT }]
  )
  begin
    socket.write(
      "POST /api/chat HTTP/1.0\r\n" \
      "Host: #{address}:#{port}\r\n" \
      "Content-Type: application/json\r\n" \
      "Content-Length: #{body.bytesize}\r\n\r\n" \
      "#{body}"
    )
    status = socket.gets
  rescue SystemCallError
    status = nil
  end
  code = status && status[%r{\AHTTP/\S+ (\d{3})}, 1]
  give_up("the tunnel closed the connection. Is Ollama running on the Mac?") if code.nil?
  # headers: the body's framing is the connection's end
  while (line = socket.gets) && line.chomp != ""
  end
  if code.to_i >= 400
    reply = JSON.parse(socket.read.to_s) rescue nil
    error = reply.is_a?(Hash) ? reply.fetch("error", "") : ""
    give_up("Ollama answered #{code}: #{error}")
  end

  $stdout.sync = true
  begin
    while (line = socket.gets)
      next if line.strip.empty?
      part = JSON.parse(line)
      if part.key?("error")
        puts
        give_up("Ollama stopped with an error: #{part["error"]}")
      end
      print(part["message"]["content"])
      if part["done"]
        puts
        return
      end
    end
  rescue JSON::ParserError, SystemCallError
    nil # a line cut short, or a reset: either way, the answer is cut off
  end
  puts
  give_up("the answer was cut off before Ollama finished it")
end
