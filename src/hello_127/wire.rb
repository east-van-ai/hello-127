# Carry TCP connections as frames over a pair of pipes: the inside half, in Ruby.
#
# The twin of wire.py's inside half, for a container with ruby and none of python3,
# node, or php. The container receives this source through `ruby -e`, then one call
# to `listen`. It uses the standard library only, runs on Ruby 3.3, and never writes
# to stdout, which is the wire. The frame format is wire.py's: a change to one lands
# in the others.

require "json"
require "socket"

OPEN = 1
DATA = 2
CLOSE = 3
HEADER_SIZE = 9
CHUNK = 65536

# Print one line to stderr, since stdout belongs to the frames.
def wire_log(message)
  $stderr.write("hello-127: #{message}\n")
end

# Return one frame: kind, connection number, payload length, then the payload.
def frame(kind, conn, payload = "")
  [kind, conn, payload.bytesize].pack("CNN") + payload.b
end

# Return the first whole frame in `pending` as [kind, conn, payload, rest], or nil.
def next_frame(pending)
  return nil if pending.bytesize < HEADER_SIZE
  kind, conn, length = pending.unpack("CNN")
  finish = HEADER_SIZE + length
  return nil if pending.bytesize < finish
  [kind, conn, pending.byteslice(HEADER_SIZE, length), pending.byteslice(finish..)]
end

# Write all of `bytes` to `io`, blocking while it is full. False once it fails.
def write_all(io, bytes)
  io.write(bytes)
  true
rescue IOError, SystemCallError
  false
end

# Bind each [address, port] in order, or log why one cannot and exit 1.
def bind_all(listeners)
  listeners.map do |address, port|
    server = TCPServer.new(address, port)
    wire_log("inside: listening on #{address}:#{port}")
    server
  rescue Errno::EADDRINUSE
    wire_log("inside: cannot listen on #{address}:#{port}: already in use in this container")
    exit(1)
  rescue SystemCallError => error
    wire_log("inside: cannot listen on #{address}:#{port}: #{error.message.split(" - ").first}")
    exit(1)
  end
end

# Dial the target at `index` in `targets`. Return the socket, or nil after logging why.
def dial(conn, index, targets)
  address, port = targets[index]
  if address.nil?
    wire_log("connection #{conn}: dial failed: no target number #{index}")
    return nil
  end
  TCPSocket.new(address, port)
rescue SystemCallError => error
  wire_log("connection #{conn}: dial failed: #{error.message.split(" - ").first}")
  nil
end

# Listen on each [address, port] in `listeners`, and dial `targets` on request.
#
# The helper's OPEN carries its listener's index in `listeners`, so the Mac side
# knows where to dial. The Mac's OPEN carries an index in `targets`, the address and
# port to dial in here. A listener that cannot bind ends the helper, with no partial
# tunnel.
#
# One IO.select loop watches stdin, the listeners, and every socket still reading.
# Writes block, so a full stdout stalls the sockets, and a full socket stalls stdin,
# as in the other wires. The dial blocks too, so no DATA frame overtakes its own
# connection's dial.
def listen(listeners, targets)
  servers = bind_all(listeners)
  $stdin.binmode
  $stdout.binmode
  $stdout.sync = true # a frame held in Ruby's buffer never reaches the Mac
  sockets = {} # conn -> socket
  reading = {} # conn -> socket, while its read direction is open
  remaining = {} # conn -> directions still open, from 2 down to 0
  next_conn = 1 # odd inside, even on the Mac
  pending = "".b

  # Count one direction of a connection as done, and drop it once both are.
  finish_half = lambda do |conn|
    next unless remaining.key?(conn)
    remaining[conn] -= 1
    if remaining[conn].zero?
      sockets.delete(conn).close
      remaining.delete(conn)
    end
  end

  catch(:input_ended) do
    loop do
      ready, = IO.select([$stdin, *servers, *reading.values])
      ready.each do |io|
        if io.equal?($stdin)
          begin
            pending << $stdin.readpartial(CHUNK)
          rescue EOFError
            throw :input_ended
          end
          while (got = next_frame(pending))
            kind, conn, payload, pending = got
            if kind == OPEN
              socket = dial(conn, payload.unpack1("n"), targets)
              if socket.nil?
                write_all($stdout, frame(CLOSE, conn))
              else
                sockets[conn] = socket
                reading[conn] = socket
                remaining[conn] = 2
              end
              next
            end
            socket = sockets[conn]
            next if socket.nil?
            if kind == DATA
              write_all(socket, payload)
            elsif kind == CLOSE
              begin
                socket.close_write
              rescue IOError, SystemCallError
                nil
              end
              finish_half.call(conn)
            end
          end
        elsif (index = servers.index(io))
          socket = io.accept_nonblock(exception: false)
          next if socket == :wait_readable
          conn = next_conn
          next_conn += 2
          sockets[conn] = socket
          reading[conn] = socket
          remaining[conn] = 2
          write_all($stdout, frame(OPEN, conn, [index].pack("n")))
        else
          conn = reading.key(io)
          begin
            write_all($stdout, frame(DATA, conn, io.readpartial(CHUNK)))
          rescue EOFError, SystemCallError
            # an end or a reset
            reading.delete(conn)
            write_all($stdout, frame(CLOSE, conn))
            finish_half.call(conn)
          end
        end
      end
    end
  end

  sockets.each_value(&:close)
  servers.each(&:close)
  wire_log("inside: input ended, helper exiting")
end
