"""A line that starts with ``!``: the rest runs in the user's own shell, on
the machine the client runs on and in its working folder. What it prints
goes into the history line by line, as it comes; nothing of it reaches the
service, the chat or the model. There is no time limit: the interrupt key
ends the command that runs, and the history says so.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading

from cli.interfaces import Context

# The first character of a line that runs in the shell instead of going out
# as a message.
MARK = "!"

# The return code for a command that could not be started at all — what a
# shell answers for a command it does not find.
NOT_RUN = 127


def is_shell_line(text: str) -> bool:
    return text.startswith(MARK)


def invocation(command: str) -> list[str]:
    """The command as the user's own shell runs it — the one the terminal
    gave them, or the system's where none is named; on Windows the command
    interpreter."""
    if sys.platform == "win32":
        return ["cmd", "/c", command]
    return [os.environ.get("SHELL") or "/bin/sh", "-c", command]


class Shell:
    """Runs the shell lines, and ends the one that runs when told to."""

    def __init__(self) -> None:
        self._running: subprocess.Popen[str] | None = None
        self._stopped = False
        self._lock = threading.Lock()

    def run(self, ctx: Context, line: str) -> int:
        """Runs what follows the mark and writes every line it prints — on
        either of its outputs — into the history as it comes. Below the
        output stands a return code other than zero, or that the command
        was stopped. Returns the code; a line with nothing behind the mark
        runs nothing."""
        command = line[len(MARK) :].strip()
        if not command:
            return 0
        try:
            process = subprocess.Popen(
                invocation(command),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                # Its own group, so that ending it ends every process it
                # started — a pipeline, a script and what the script runs.
                start_new_session=True,
            )
        except OSError as error:
            ctx.renderer.error(str(error))
            return NOT_RUN
        with self._lock:
            self._running = process
            self._stopped = False
        if process.stdout is not None:
            with process.stdout:
                for printed in process.stdout:
                    ctx.renderer.shell_line(printed.rstrip("\r\n"))
        code = process.wait()
        with self._lock:
            self._running = None
            stopped = self._stopped
        if stopped:
            ctx.renderer.remark(ctx.texts.t("cli.shell_stopped"))
        elif code:
            ctx.renderer.remark(ctx.texts.t("cli.shell_exit", code=code))
        return code

    def interrupt(self) -> bool:
        """Ends the command that runs right now, with everything it
        started. Whether there was one."""
        with self._lock:
            process = self._running
            if process is None:
                return False
            self._stopped = True
        try:
            if sys.platform == "win32":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            # Gone by itself in the meantime: nothing left to end.
            pass
        return True
