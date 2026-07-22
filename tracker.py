"""
PC Usage Time Tracker
Monitors active/idle time using platform-appropriate APIs.
- macOS : ioreg IOHIDSystem HIDIdleTime
- Windows: GetLastInputInfo (User32.dll)
"""

import sys
import time
import json
import platform
import subprocess
import ctypes
import threading
import argparse
from datetime import datetime, date
from pathlib import Path

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_IDLE_THRESHOLD_SEC = 60
DEFAULT_POLL_INTERVAL_SEC  = 5
LOG_FILE                   = Path(__file__).parent / "usage_log.json"
# ─────────────────────────────────────────────────────────────────────────────


# ── Platform idle-time detection ──────────────────────────────────────────────

def _idle_seconds_macos() -> float:
    cmd = "ioreg -c IOHIDSystem | awk '/HIDIdleTime/ {print $NF/1000000000; exit}'"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    raw = result.stdout.strip()
    return float(raw) if raw else 0.0


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def _idle_seconds_windows() -> float:
    lii = _LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))   # type: ignore[attr-defined]
    elapsed_ms = ctypes.windll.kernel32.GetTickCount() - lii.dwTime  # type: ignore[attr-defined]
    return elapsed_ms / 1000.0


def get_idle_seconds() -> float:
    os_name = platform.system()
    if os_name == "Darwin":
        return _idle_seconds_macos()
    elif os_name == "Windows":
        return _idle_seconds_windows()
    else:
        raise RuntimeError(f"Unsupported platform: {os_name}")


# ── Session tracking ───────────────────────────────────────────────────────────

class UsageTracker:
    def __init__(
        self,
        idle_threshold: int = DEFAULT_IDLE_THRESHOLD_SEC,
        poll_interval:  int = DEFAULT_POLL_INTERVAL_SEC,
        log_file: Path      = LOG_FILE,
    ):
        self.idle_threshold = idle_threshold   # mutable at runtime
        self.poll_interval  = poll_interval
        self.log_file       = log_file

        self._lock              = threading.Lock()
        self._stop_event        = threading.Event()
        self._session_start: float | None = None
        self._was_idle          = False
        self._today_active_sec  = 0.0
        self._today_date        = date.today()

    # ── Dynamic threshold control ──────────────────────────────────────────────

    def set_idle_threshold(self, seconds: int) -> None:
        with self._lock:
            self.idle_threshold = seconds
        print(f"\n[{_now()}] Idle threshold updated → {seconds}s\n", flush=True)

    def _input_listener(self) -> None:
        """Background thread: reads commands from stdin while tracker runs."""
        _print_commands()
        while not self._stop_event.is_set():
            try:
                raw = input()
            except EOFError:
                break

            line = raw.strip().lower()
            if not line:
                continue

            # Accept bare number or "set <n>"
            token = line.removeprefix("set").strip()
            if token.isdigit():
                val = int(token)
                if val < 1:
                    print("  Threshold must be ≥ 1 second.", flush=True)
                else:
                    self.set_idle_threshold(val)
            elif line in ("status", "s"):
                self._print_status()
            elif line in ("help", "h", "?"):
                _print_commands()
            elif line in ("quit", "q", "exit"):
                self._stop_event.set()
            else:
                print(f"  Unknown command: '{raw}'. Type 'help' for options.", flush=True)

    def _print_status(self) -> None:
        with self._lock:
            threshold = self.idle_threshold
        total = self._fmt_hms(self._today_active_sec)
        state = "idle" if self._was_idle else "active"
        print(
            f"\n  State          : {state}\n"
            f"  Idle threshold : {threshold}s\n"
            f"  Today active   : {total}\n",
            flush=True,
        )

    # ── Logging ────────────────────────────────────────────────────────────────

    def _load_log(self) -> dict:
        if self.log_file.exists():
            with open(self.log_file) as f:
                return json.load(f)
        return {}

    def _save_log(self, data: dict) -> None:
        with open(self.log_file, "w") as f:
            json.dump(data, f, indent=2)

    def _record_session(self, start: float, end: float) -> None:
        duration = end - start
        if duration < 1:
            return

        log     = self._load_log()
        day_key = str(date.today())
        entry   = {
            "start":    datetime.fromtimestamp(start).isoformat(timespec="seconds"),
            "end":      datetime.fromtimestamp(end).isoformat(timespec="seconds"),
            "duration": round(duration, 1),
        }
        log.setdefault(day_key, {"sessions": [], "total_active_sec": 0})
        log[day_key]["sessions"].append(entry)
        log[day_key]["total_active_sec"] = round(
            log[day_key]["total_active_sec"] + duration, 1
        )
        self._save_log(log)
        self._today_active_sec += duration

    # ── State machine ──────────────────────────────────────────────────────────

    def _on_became_active(self) -> None:
        self._session_start = time.time()
        self._was_idle      = False
        print(f"[{_now()}] Active  — session started", flush=True)

    def _on_became_idle(self) -> None:
        if self._session_start is not None:
            self._record_session(self._session_start, time.time())
        self._session_start = None
        self._was_idle      = True
        total = self._fmt_hms(self._today_active_sec)
        print(f"[{_now()}] Idle    — today's active time: {total}", flush=True)

    def run(self) -> None:
        with self._lock:
            threshold = self.idle_threshold
        print(
            f"Tracker started  |  idle threshold={threshold}s  "
            f"poll={self.poll_interval}s  log={self.log_file}\n"
        )

        listener = threading.Thread(target=self._input_listener, daemon=True)
        listener.start()

        try:
            while not self._stop_event.is_set():
                today = date.today()
                if today != self._today_date:
                    if self._session_start is not None:
                        self._record_session(self._session_start, time.time())
                        self._session_start = time.time()
                    self._today_active_sec = 0.0
                    self._today_date       = today

                idle_sec = get_idle_seconds()
                with self._lock:
                    threshold = self.idle_threshold
                is_idle = idle_sec >= threshold

                if is_idle and not self._was_idle:
                    self._on_became_idle()
                elif not is_idle and self._was_idle:
                    self._on_became_active()
                elif not is_idle and self._session_start is None:
                    self._on_became_active()

                time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            pass

        self._stop_event.set()
        print("\nStopping…")
        if self._session_start is not None:
            self._record_session(self._session_start, time.time())
        self._print_summary()

    # ── Reporting ──────────────────────────────────────────────────────────────

    def _print_summary(self) -> None:
        log = self._load_log()
        print("\n─── Today's summary ───────────────────────────────")
        day_key = str(date.today())
        if day_key in log:
            entry = log[day_key]
            total = self._fmt_hms(entry["total_active_sec"])
            n     = len(entry["sessions"])
            print(f"  Active sessions : {n}")
            print(f"  Total active    : {total}")
            for i, s in enumerate(entry["sessions"], 1):
                dur = self._fmt_hms(s["duration"])
                print(f"  [{i:2}] {s['start']}  →  {s['end']}  ({dur})")
        else:
            print("  No data recorded today.")
        print("────────────────────────────────────────────────────")

    @staticmethod
    def _fmt_hms(seconds: float) -> str:
        s = int(seconds)
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}"


# ── Utility ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _print_commands() -> None:
    print(
        "  Commands while running:\n"
        "    <number>   — set idle threshold in seconds  (e.g. 120)\n"
        "    set <n>    — same as above\n"
        "    status     — show current state and settings\n"
        "    help       — show this message\n"
        "    quit       — stop tracker\n",
        flush=True,
    )


def show_report() -> None:
    if not LOG_FILE.exists():
        print("No log file found.")
        return

    with open(LOG_FILE) as f:
        log = json.load(f)

    print("\n─── Usage report ───────────────────────────────────")
    for day, data in sorted(log.items()):
        total = UsageTracker._fmt_hms(data["total_active_sec"])
        n     = len(data["sessions"])
        print(f"  {day}  |  sessions: {n:3}  |  active: {total}")
    print("────────────────────────────────────────────────────\n")


# ── Entry point ────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PC usage time tracker")
    parser.add_argument(
        "--idle", "-i",
        type=int,
        default=DEFAULT_IDLE_THRESHOLD_SEC,
        metavar="SECONDS",
        help=f"idle threshold in seconds (default: {DEFAULT_IDLE_THRESHOLD_SEC})",
    )
    parser.add_argument(
        "--poll", "-p",
        type=int,
        default=DEFAULT_POLL_INTERVAL_SEC,
        metavar="SECONDS",
        help=f"polling interval in seconds (default: {DEFAULT_POLL_INTERVAL_SEC})",
    )
    parser.add_argument(
        "--report", "-r",
        action="store_true",
        help="print multi-day usage report and exit",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.report:
        show_report()
    else:
        if args.idle < 1:
            print("--idle must be ≥ 1 second.")
            sys.exit(1)
        tracker = UsageTracker(idle_threshold=args.idle, poll_interval=args.poll)
        tracker.run()
