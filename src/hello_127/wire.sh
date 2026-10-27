# Carry TCP connections as frames over a pair of pipes: the inside half, in BusyBox sh.
#
# The twin of wire.py's inside half, for a container with busybox and no interpreter.
# The container receives this source through `busybox sh -c`, then one call to
# `listen`, its arguments as words. It uses only BusyBox applets, runs on BusyBox 1.36
# with the full nc, and never writes to stdout, which is the wire. The frame format is
# wire.py's: a change to one lands in the others.
#
# Each socket lives in its own `nc -e` child, which bridges it to two FIFOs, u.PID up
# and d.PID down. Subshells of this helper do the framing. The child cannot half-close
# its socket, so a CLOSE from the Mac only stops the bytes; the socket ends with the
# child, once both directions are done.

# Print one line to stderr, since stdout belongs to the frames.
wire_log() {
    echo "hello-127: $*" >&2
}

# Print the octal escapes of N as four big-endian bytes, for printf.
u32() {
    printf '\\%03o\\%03o\\%03o\\%03o' \
        $(($1 >> 24 & 255)) $(($1 >> 16 & 255)) $(($1 >> 8 & 255)) $(($1 & 255))
}

# Write one frame, KIND CONN PAYLOAD-FILE, to the wire in a single write.
#
# One write of 4096 bytes or fewer to a pipe is atomic, so frames from many
# subshells never interleave. Only the dispatcher writes bigger frames, never
# alongside a pump of the same connection.
frame() {
    _n=$(stat -c %s "$3")
    _f=$D/f.$2.$1
    { printf "\\$(printf %03o "$1")$(u32 "$2")$(u32 "$_n")"; cat "$3"; } > "$_f"
    dd if="$_f" bs=$((_n + 9)) count=1 2>/dev/null >> "$D/out"
}

# The nc -e child. It starts as a fresh shell with only its environment, so no
# functions. BusyBox cat from a socket into a FIFO holds the bytes until EOF, so dd.
# If the socket stops taking bytes, a drain empties d.PID until the Mac's CLOSE, or the
# dispatcher's next DATA frame would block on a full FIFO. The drain opens it for
# reading and writing, so the open never waits, and keeps no hold on the socket.
CHILD='mkfifo "$D/u.$$" "$D/d.$$"
echo "$IDX $$" > "$NOTE"
{
    busybox dd bs=65536 if="$D/d.$$" 2>/dev/null || {
        busybox dd bs=65536 of=/dev/null 0<> "$D/d.$$" > /dev/null 2>&1 &
        echo $! > "$D/drain.$$"
    }
} < /dev/null &
busybox dd bs=4096 of="$D/u.$$" 2>/dev/null
wait'

# Copy connection CONN's socket bytes, from child PID, into DATA frames, then CLOSE.
#
# 4087 bytes of payload keep each frame within one atomic pipe write.
pump() {
    _c=$D/c.$1
    exec 5< "$D/u.$2"
    while :; do
        dd bs=4087 count=1 of="$_c" <&5 2>/dev/null
        [ -s "$_c" ] || break
        frame 2 "$1" "$_c"
    done
    : > "$_c"
    frame 3 "$1" "$_c"
}

# Hold connection CONN's down FIFO, from child PID, open until the Mac's CLOSE.
#
# Without a writer between frames, the child's reader would see an end after one.
hold() {
    echo "$2" > "$D/pid.$1"
    sleep 2147483647 1<> "$D/d.$2" &
    echo $! > "$D/hold.$1"
}

# Number each accepted connection, announce it with its listener, and pump it.
#
# One loop hands out every number, 1, 3, 5, so no lock. OPEN goes out before the
# pump starts, or the first DATA frame would overtake it.
accept_loop() {
    _conn=1
    while read -r _idx _pid; do
        hold "$_conn" "$_pid"
        printf "\\$(printf %03o $((_idx >> 8)))\\$(printf %03o $((_idx & 255)))" > "$D/o.$_conn"
        frame 1 "$_conn" "$D/o.$_conn"
        pump "$_conn" "$_pid" &
        _conn=$((_conn + 2))
    done <> "$D/acc"
}

# Dial target INDEX for the Mac's connection CONN, and wait for it inline.
#
# The dial waits on its own FIFO for the child's PID, or for `fail` from an nc that
# could not connect, so no DATA frame overtakes its own connection's dial.
dial() {
    set -- $targets
    _idx=$idx
    if [ "$_idx" -ge "$#" ]; then
        wire_log "connection $conn: dial failed: no target number $_idx"
        : > "$D/p"
        frame 3 "$conn" "$D/p"
        return
    fi
    shift "$_idx"
    _addr=${1%:*}
    _port=${1##*:}
    mkfifo "$D/dial.$conn"
    (
        D=$D IDX=0 NOTE=$D/dial.$conn \
            busybox nc "$_addr" "$_port" -e busybox sh -c "$CHILD" 2>/dev/null \
            || echo "x fail" > "$D/dial.$conn"
    ) &
    read -r _ _pid < "$D/dial.$conn"
    if [ "$_pid" = fail ]; then
        wire_log "connection $conn: dial failed: $_addr:$_port refused"
        : > "$D/p"
        frame 3 "$conn" "$D/p"
        return
    fi
    hold "$conn" "$_pid"
    pump "$conn" "$_pid" &
}

# Print every process below PID.
#
# sh has no local variables, so the recursion would overwrite `_child`: print it first.
tree() {
    for _child in $(ps -o pid,ppid | awk -v p="$1" '$2 == p { print $1 }'); do
        echo "$_child"
        tree "$_child"
    done
}

# Stop every process this helper started, drop its files, and exit with CODE.
#
# Never `kill 0`: the helper may share its process group with whoever started it. A
# drain outlives its child, so its pid comes from its file instead of the tree.
quit() {
    _all="$(tree $$) $(cat "$D"/drain.* 2>/dev/null)"
    kill $_all 2>/dev/null
    rm -rf "$D"
    exit "$1"
}

# Bind listener INDEX on ADDRESS:PORT, or log why it cannot and quit with 1.
#
# nc -v says `listening on` once the bind holds, and dies with the reason if not.
bind_one() {
    D=$D IDX=$1 NOTE=$D/acc \
        busybox nc -v -lk -s "$2" -p "$3" -e busybox sh -c "$CHILD" 2> "$D/l.$1" &
    _nc=$!
    while [ ! -s "$D/l.$1" ] && kill -0 "$_nc" 2>/dev/null; do
        sleep 0.01
    done
    if grep -q '^listening on' "$D/l.$1" && kill -0 "$_nc" 2>/dev/null; then
        wire_log "inside: listening on $2:$3"
        return
    fi
    _why=$(sed -n 's/^nc: bind: //p' "$D/l.$1")
    [ "$_why" = "Address in use" ] && _why="already in use in this container"
    wire_log "inside: cannot listen on $2:$3: ${_why:-$(head -n 1 "$D/l.$1")}"
    quit 1
}

# Listen on each ADDRESS:PORT in LISTENERS, and dial TARGETS on request.
#
# Both are words: `127.0.0.1:11434 127.0.0.1:8000`. The helper's OPEN carries its
# listener's index in LISTENERS, so the Mac side knows where to dial. The Mac's OPEN
# carries an index in TARGETS, the address and port to dial in here. A listener that
# cannot bind ends the helper, with no partial tunnel. A DATA frame waits for its
# child to read, so a full socket stalls stdin, as in the other wires.
listen() {
    targets=$2
    D=$(mktemp -d)
    mkfifo "$D/out" "$D/acc"
    cat "$D/out" &
    exec 3> "$D/out" >&2
    _i=0
    for _spec in $1; do
        bind_one "$_i" "${_spec%:*}" "${_spec##*:}"
        _i=$((_i + 1))
    done
    accept_loop &
    while _hdr=$(dd iflag=fullblock bs=9 count=1 2>/dev/null | od -An -tu1 -v); [ -n "$_hdr" ]; do
        set -- $_hdr
        kind=$1
        conn=$((($2 << 24) | ($3 << 16) | ($4 << 8) | $5))
        _len=$((($6 << 24) | ($7 << 16) | ($8 << 8) | $9))
        if [ "$_len" -gt 0 ]; then
            dd iflag=fullblock bs="$_len" count=1 of="$D/p" 2>/dev/null
        else
            : > "$D/p"
        fi
        case $kind in
            1)
                set -- $(od -An -tu1 "$D/p")
                idx=$((($1 << 8) | $2))
                dial
                ;;
            2)
                [ -f "$D/pid.$conn" ] && cat "$D/p" 1<> "$D/d.$(cat "$D/pid.$conn")"
                ;;
            3)
                [ -f "$D/hold.$conn" ] && kill "$(cat "$D/hold.$conn")" \
                    $(cat "$D/drain.$(cat "$D/pid.$conn")" 2>/dev/null) 2>/dev/null
                ;;
        esac
    done
    wire_log "inside: input ended, helper exiting"
    quit 0
}
