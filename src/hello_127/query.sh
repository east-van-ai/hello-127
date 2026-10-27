# Check from inside a container that Ollama answers, and print what it says.
#
# A lesser twin of query.py, for a container with busybox and no interpreter. BusyBox
# has no JSON, so there is no chat to post or read: the probe asks for `/`, and Ollama
# answers `Ollama is running`. The container receives this source through
# `busybox sh -c`, then one call to `ask`. It runs on BusyBox 1.36, and prints the
# same connection failure lines as query.py.

# Print one line to stderr and exit 1.
give_up() {
    echo "hello-127: $*" >&2
    exit 1
}

# Ask ADDRESS:PORT for `/` and print the body, with a newline.
#
# wget says what went wrong in one stderr line, which maps onto the shared lines.
ask() {
    _out=$(busybox wget -q -O - "http://$1:$2/" 2>&1)
    if [ $? -eq 0 ]; then
        printf '%s\n' "$_out"
        return
    fi
    _said=$(printf '%s\n' "$_out" | grep '^wget: ' | tail -n 1)
    case $_said in
        *"Connection refused"*)
            give_up "nothing answers on $1:$2 here. Is the tunnel running?" ;;
        *"server returned error: HTTP/"*)
            _status=${_said#*HTTP/* }
            give_up "Ollama answered ${_status%% *}" ;;
        *"error getting response"* | *"Connection reset"*)
            give_up "the tunnel closed the connection. Is Ollama running on the Mac?" ;;
    esac
    give_up "cannot reach $1:$2: ${_said#wget: }"
}
