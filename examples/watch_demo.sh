#!/usr/bin/env bash
# Example: Set up a CNS echo watch loop between two agents.
#
# This script creates temp inbox/outbox directories, drops a few test
# signals, and runs cns-echo in one-shot mode to process them.
#
# Usage:
#   bash examples/watch_demo.sh

set -euo pipefail

WORKDIR=$(mktemp -d)
INBOX="$WORKDIR/inbox"
OUTBOX="$WORKDIR/outbox"
mkdir -p "$INBOX" "$OUTBOX"

echo "=== CNS Echo Watch Demo ==="
echo "Inbox:  $INBOX"
echo "Outbox: $OUTBOX"
echo ""

# Drop three test signals
for i in 1 2 3; do
    cat > "$INBOX/signal_${i}.json" << EOF
{
    "header": {
        "origin_id": "test-agent-${i}",
        "timestamp": "2026-08-11T08:0${i}:00Z",
        "priority": "MEDIUM",
        "sequence_id": ${i}
    },
    "body": {
        "intent": "QUERY",
        "payload": {
            "type": "text",
            "data": "test signal ${i}"
        }
    },
    "signature": {
        "type": "sha256",
        "checksum": "verified"
    }
}
EOF
done

echo "Dropped 3 test signals into inbox."
echo ""

# Run cns-echo in one-shot mode
python -m cns_echo --inbox "$INBOX" --outbox "$OUTBOX"

echo ""
echo "Responses written to outbox:"
ls -la "$OUTBOX/"

echo ""
echo "Cleaning up..."
rm -rf "$WORKDIR"
echo "Done."
