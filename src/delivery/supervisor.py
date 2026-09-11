"""The supervisor: starts and stops the demo's managed child processes.

Every managed command is a wrapper. `uv run python -m delivery.worker` spawns a
child that does the real work, so each process is launched into its own session
and stopped by signalling the whole process group. Signalling only the pid we
spawned would leave that forked child alive and reparented, still holding its
port or still polling its task queue.

That leftover matters more than it looks. A stray stub announces itself with a
bind error, but a stray Worker says nothing at all: it keeps running orders, so
"kill the Worker" appears to do nothing and the demo quietly teaches the
opposite of its lesson.
"""

import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProcessDefinition:
    """How to launch a managed process.

    `command` is run through a shell, the same way the Makefile runs it. `match`
    is a pattern that recognises an instance already running, for the case where
    the supervisor has no handle on it (started by hand, or left behind by an
    earlier run).

    The match has to appear in the command line of *every* process in the tree,
    not just the outer one. That holds for these commands because each level
    carries the module path: both `uv run python -m delivery.worker` and the
    Python child it forks contain `delivery.worker`.
    """

    command: str
    match: str


class Supervisor:
    """Starts and stops the managed processes, one entry per name.

    Each process writes to its own file under `log_dir`.
    """

    def __init__(self, processes: dict[str, ProcessDefinition], log_dir) -> None:
        self._processes = processes
        self._log_dir = Path(log_dir)
        self._running: dict[str, subprocess.Popen] = {}
        self._logs: dict[str, object] = {}

    def start(self, name: str) -> int:
        """Launch the process, returning the pid of the command we spawned.

        Makes sure no earlier instance survives first, both the one we hold a
        handle for and any we don't, so we never end up running two. Two
        instances is the quiet failure: a second Worker polling the same task
        queue keeps orders moving, so stopping "the" Worker appears to do
        nothing at all.
        """
        definition = self._processes[name]

        self.stop(name)
        self._kill_untracked(definition.match)

        log_file = self._open_log(name)

        # Its own session, so stopping can signal the whole group and take the
        # forked child along with it.
        process = subprocess.Popen(
            definition.command,
            shell=True,
            start_new_session=True,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=self._child_environment(),
        )
        self._running[name] = process
        self._logs[name] = log_file

        return process.pid

    @staticmethod
    def _child_environment() -> dict[str, str]:
        """The environment a managed process runs in.

        Built on top of our own environment rather than replacing it, since the
        commands run through `uv` and need the project context they inherited.

        `PYTHONUNBUFFERED` earns its place because stopping is a `kill -9`.
        Python block-buffers stdout when it points at a file, so whatever a
        long-running service printed at startup would be thrown away with the
        process instead of reaching its log.
        """
        return {**os.environ, "PYTHONUNBUFFERED": "1"}

    def _open_log(self, name: str):
        """The process's own log file, opened to append.

        Appending keeps the earlier runs, so the sequence across a restart
        survives rather than being overwritten by the run that followed it.
        """
        self._log_dir.mkdir(parents=True, exist_ok=True)

        return open(self._log_dir / f"{name}.log", "a")

    def _kill_untracked(self, match: str) -> None:
        """Kill instances the supervisor holds no handle for.

        Started by hand, or left behind by a supervisor that died. Each pid is
        signalled on its own rather than by group, because these processes are
        not ours and their groups are not ours to assume anything about.
        """
        found = subprocess.run(
            ["pgrep", "-f", match],
            capture_output=True,
            text=True,
        )

        for matched in found.stdout.split():
            matched_pid = int(matched)
            if matched_pid == os.getpid():
                continue

            try:
                os.kill(matched_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # It went away between the search and the signal.

    def is_running(self, name: str) -> bool:
        """Whether the managed process is currently executing.

        This asks `poll()` rather than checking whether the pid exists. An
        exited process stays in the process table as a zombie until something
        reaps it, so a pid check would answer "running" for a process that has
        already stopped. `poll()` reaps it and tells the truth.
        """
        process = self._running.get(name)
        if process is None:
            return False

        return process.poll() is None

    def stop(self, name: str) -> None:
        """Make sure the process is not running, whatever state it is in.

        Total on purpose: alive, already exited on its own, or never started at
        all. Callers shouldn't have to check first, and neither should the
        cleanup that runs after something else has already gone wrong.

        Signals the whole process group so the forked child dies too.
        """
        process = self._running.pop(name, None)
        log_file = self._logs.pop(name, None)

        if process is not None:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass  # It exited on its own, so there is no group left to signal.

            process.wait()

        if log_file is not None:
            log_file.close()
