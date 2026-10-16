"""A stand-in for the voice process (app/voice_worker.py) that speaks its
protocol and nothing else: it writes a marker file for a piece and notes
every request in the file the test names, so the test can count loads.

The way it behaves comes from the environment of the process:
``VOICE_STUB_MODE`` is empty (works), ``load_fails``, ``load_dies``,
``speak_fails``, ``speak_dies`` or ``slow_load`` (the load takes
``VOICE_STUB_DELAY`` seconds).
"""

from __future__ import annotations

import json
import os
import sys
import time

LOG = os.environ.get("VOICE_STUB_LOG")
MODE = os.environ.get("VOICE_STUB_MODE", "")


def note(text: str) -> None:
    if LOG:
        with open(LOG, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def main() -> int:
    for line in sys.stdin:
        request = json.loads(line)
        operation = request.get("op")
        if operation == "quit":
            note("quit")
            break
        if operation == "load":
            note("load " + json.dumps({k: request.get(k) for k in ("model", "mmproj", "speaker")}))
            if MODE == "load_dies":
                os._exit(3)
            if MODE == "slow_load":
                time.sleep(float(os.environ.get("VOICE_STUB_DELAY", "1")))
            if MODE == "load_fails":
                reply = {"ok": False, "error": "layout_unknown"}
            else:
                reply = {"ok": True, "rate": 24000}
        elif operation == "speak":
            note("speak " + json.dumps({k: request.get(k) for k in ("text", "language", "sampling")}))
            if MODE == "speak_dies":
                os._exit(4)
            if MODE == "speak_fails":
                reply = {"ok": False, "error": "prompt_failed"}
            else:
                with open(request["out"], "wb") as handle:
                    handle.write(b"RIFFstub:" + str(request["text"]).encode())
                reply = {"ok": True, "frames": 3}
        else:
            reply = {"ok": False, "error": "unknown_operation"}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()
    note("exit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
