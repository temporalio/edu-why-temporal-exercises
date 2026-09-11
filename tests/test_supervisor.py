"""The supervisor owns the demo's child processes: it starts them, stops them,
and reports whether they are running.

Every managed command is a wrapper. `uv run python -m delivery.worker` spawns a
child that does the real work, so a stop that kills only the process the
supervisor spawned leaves that child alive, still holding its port or still
polling its task queue. A leftover stub announces itself with a bind error; a
leftover Worker says nothing at all and quietly keeps running orders, which is
the failure worth guarding against.

These tests use a stand-in command with the same shape, a shell that forks a
child and waits on it, so they stay fast and need no Temporal, no uvicorn, and
no ports.
"""

import os
import signal
import subprocess
import time

import pytest

from delivery.supervisor import ProcessDefinition, Supervisor

# Stands in for a managed command. The shell forks `sleep` and waits on it, so
# the tree is two processes deep, the same shape as `uv run python -m ...`.
STAND_IN_COMMAND = "sleep 300 & wait"
STAND_IN_MATCH = "[s]leep 300"

STAND_IN_PROCESSES = {
    "stand-in": ProcessDefinition(
        command=STAND_IN_COMMAND,
        match=STAND_IN_MATCH,
    ),
    "short-lived": ProcessDefinition(
        command="exit 0",
        match="[n]othing-matches-this",
    ),
}


@pytest.fixture
def supervisor(tmp_path):
    """A supervisor for one test, with whatever it started stopped afterwards.

    The teardown runs even when an assertion fails, so a broken test can't
    strand a process and contaminate the next one.
    """
    supervisor = Supervisor(dict(STAND_IN_PROCESSES), log_dir=tmp_path / "logs")

    yield supervisor

    for name in STAND_IN_PROCESSES:
        supervisor.stop(name)


@pytest.fixture
def stray_stand_in():
    """An instance started outside the supervisor, as if by hand.

    Cleaned up here whatever the test proves, since the supervisor fixture only
    knows about processes it started itself.
    """
    started = subprocess.Popen(STAND_IN_COMMAND, shell=True, start_new_session=True)

    yield started

    try:
        os.killpg(os.getpgid(started.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass


def is_executing(pid: int) -> bool:
    """Whether the process is still running, as opposed to merely still listed.

    Deliberately not `os.kill(pid, 0)`. A killed child of this test process sits
    in the table as a zombie until something reaps it, and a pid check reports
    it as alive: measured directly, the same pid reads state 'Z' while
    `os.kill` still succeeds. That is the same trap the supervisor has to avoid,
    so the tests must not fall into it either.
    """
    state = subprocess.run(
        ["ps", "-o", "state=", "-p", str(pid)],
        capture_output=True,
        text=True,
    ).stdout.strip()

    return bool(state) and not state.startswith("Z")


def wait_for_forked_child(parent_pid: int, timeout: float = 5.0) -> int:
    """The pid of the process the managed command forked, once it appears."""
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        found = subprocess.run(
            ["pgrep", "-P", str(parent_pid)],
            capture_output=True,
            text=True,
        )
        if found.stdout.strip():
            return int(found.stdout.split()[0])
        time.sleep(0.05)

    raise AssertionError(f"the managed command never forked a child (parent {parent_pid})")


def wait_until_stopped(pid: int, timeout: float = 5.0) -> bool:
    """Wait for the process to stop executing, reaped or not."""
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if not is_executing(pid):
            return True
        time.sleep(0.05)

    return False


def test_stop_kills_the_forked_child_too(supervisor):
    """Stopping takes the whole process group, not just the process we spawned.

    Killing only the spawned pid leaves the forked child alive and reparented,
    still holding whatever it held. That is the orphan this supervisor exists to
    prevent.
    """
    parent_pid = supervisor.start("stand-in")
    child_pid = wait_for_forked_child(parent_pid)

    supervisor.stop("stand-in")

    assert wait_until_stopped(parent_pid), "the process the supervisor started is still alive"
    assert wait_until_stopped(child_pid), (
        "the forked child outlived the stop; stop the process group, not the pid"
    )


def test_reports_running_while_the_process_is_alive(supervisor):
    supervisor.start("stand-in")

    assert supervisor.is_running("stand-in") is True


def test_reports_stopped_once_the_process_exits_on_its_own(supervisor):
    """A process that dies without being stopped must report as stopped.

    Nothing has reaped it yet, so its pid lingers in the process table as a
    zombie and a plain existence check would still answer "running". That is the
    lie the panel must never tell: a green Worker with nothing executing.
    """
    pid = supervisor.start("short-lived")
    wait_until_stopped(pid)

    assert supervisor.is_running("short-lived") is False


def test_stopping_an_already_exited_process_is_safe(supervisor):
    """Stop has to be total: it makes sure nothing is running, whatever the state.

    The process may have crashed on its own, so signalling its group would hit a
    pid that no longer exists. Callers shouldn't have to check first, and test
    teardown shouldn't blow up while cleaning up after a failure.
    """
    pid = supervisor.start("short-lived")
    wait_until_stopped(pid)

    supervisor.stop("short-lived")

    assert supervisor.is_running("short-lived") is False


def test_stopping_something_never_started_is_safe(supervisor):
    supervisor.stop("stand-in")

    assert supervisor.is_running("stand-in") is False


def test_start_kills_an_instance_it_does_not_own(supervisor, stray_stand_in):
    """Starting makes sure the old instance is dead first, rather than joining it.

    This is the case we hit for real: something started by hand, or left behind
    by an earlier run, that the supervisor holds no handle for. Starting
    alongside it would leave two Workers polling the same task queue, which
    Temporal is perfectly happy with, so "kill the Worker" would appear to do
    nothing and the chapter would teach the opposite of its lesson.
    """
    stray_child_pid = wait_for_forked_child(stray_stand_in.pid)

    supervisor.start("stand-in")

    assert wait_until_stopped(stray_stand_in.pid), "the stray instance survived the start"
    assert wait_until_stopped(stray_child_pid), "the stray's forked child survived the start"
    assert supervisor.is_running("stand-in") is True


def test_everything_a_process_says_goes_to_its_own_log(tmp_path):
    """Each process gets its own file, carrying both of its streams.

    These logs are for debugging, not for learners: in a no-code course the
    panel is the only thing they touch. They earn their place when four
    services are running at once and one of them did not come back, which is
    unreadable if every service interleaves into the supervisor's own output.

    The directory does not exist yet, so the supervisor has to create it. The
    control plane shouldn't have to prepare the ground first.
    """
    log_dir = tmp_path / "logs"
    supervisor = Supervisor(
        {
            "talker": ProcessDefinition(
                command="echo to-stdout; echo to-stderr >&2",
                match="[n]othing-matches-this",
            )
        },
        log_dir=log_dir,
    )

    pid = supervisor.start("talker")
    wait_until_stopped(pid)

    written = (log_dir / "talker.log").read_text()

    assert "to-stdout" in written
    assert "to-stderr" in written, "stderr belongs in the same file; that is where failures show up"


def test_restarting_appends_rather_than_discarding_the_last_run(tmp_path):
    """A restart keeps the previous run's output.

    The Worker is killed and restarted repeatedly in this demo, and the sequence
    across those restarts is the useful part when working out why something did
    not come back. Truncating would throw away the half that explains it.
    """
    log_dir = tmp_path / "logs"
    supervisor = Supervisor(
        {
            "talker": ProcessDefinition(
                command="echo one-run",
                match="[n]othing-matches-this",
            )
        },
        log_dir=log_dir,
    )

    first_pid = supervisor.start("talker")
    wait_until_stopped(first_pid)

    second_pid = supervisor.start("talker")
    wait_until_stopped(second_pid)

    written = (log_dir / "talker.log").read_text()

    assert written.count("one-run") == 2, "the restart discarded the earlier run"


def test_output_survives_a_process_that_is_killed_rather_than_exiting(tmp_path):
    """Output has to reach the file as it happens, not when the process exits.

    Python block-buffers stdout when it points at a file, so a service that
    announces itself at startup and then runs indefinitely leaves that line
    sitting in a buffer. Stopping is a `kill -9`, which discards it, and the log
    for the process we most want to debug comes out empty. Measured directly:
    the same command captures nothing by default, and captures its line once
    the child runs unbuffered.
    """
    log_dir = tmp_path / "logs"
    supervisor = Supervisor(
        {
            "announcer": ProcessDefinition(
                command='python3 -c "print(\'announced\'); import time; time.sleep(300)"',
                match="[n]othing-matches-this",
            )
        },
        log_dir=log_dir,
    )

    supervisor.start("announcer")
    time.sleep(1.0)  # Long enough to have printed, nowhere near its own exit.

    supervisor.stop("announcer")

    written = (log_dir / "announcer.log").read_text()

    assert "announced" in written, (
        "the startup line never reached the file; buffered output dies with the process"
    )
