#!/bin/bash
# Resume a paused benchmark. Re-queues anything that was discarded by `pause.sh --now`.
rm -f ~/orch-bench/PAUSE ~/orch-bench/PAUSE_NOW
echo "resumed; the runner picks up within ~15 seconds"
