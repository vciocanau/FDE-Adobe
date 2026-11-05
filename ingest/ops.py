"""Operations (spec section 10): stage timing, memory readings and the log."""
import logging
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path


def peak_memory_mb() -> float | None:
    """Peak resident memory of this process, in MB."""
    try:
        if sys.platform == "win32":
            return _windows_peak()
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024
    except Exception:
        return None


def total_memory_mb() -> float | None:
    """Total physical memory of the machine, in MB; None when it cannot be read."""
    try:
        if sys.platform == "win32":
            return _windows_total()
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
            return int(out.stdout.strip()) / (1024 * 1024)
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / 1024
    except Exception:
        return None
    return None


def _windows_peak() -> float:
    import ctypes
    from ctypes import wintypes

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    process = ctypes.windll.kernel32.GetCurrentProcess()
    if not ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
        raise OSError("GetProcessMemoryInfo failed")
    return counters.PeakWorkingSetSize / (1024 * 1024)


def _windows_total() -> float:
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    return status.ullTotalPhys / (1024 * 1024)


class StageTimer:
    """Durations on a monotonic clock and the peak memory at the end of each stage."""

    def __init__(self):
        self._start = time.monotonic()
        self._results: dict[str, dict[str, float]] = {}

    @contextmanager
    def stage(self, name: str):
        begin = time.monotonic()
        try:
            yield
        finally:
            peak = peak_memory_mb()
            self._results[name] = {"duration_ms": round((time.monotonic() - begin) * 1000, 1),
                                   "peak_memory_mb": round(peak, 1) if peak is not None else None}

    def results(self) -> dict[str, dict[str, float]]:
        return dict(self._results)

    def total_ms(self) -> float:
        return round((time.monotonic() - self._start) * 1000, 1)


class _Formatter(logging.Formatter):
    converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created))
        stage = getattr(record, "stage", "-")
        code = getattr(record, "code", "-")
        return f"{stamp} {record.levelname} {stage} {code} {record.getMessage()}"


def setup_log(log_path: Path, console: bool = True) -> logging.Logger:
    """Log to the file and, unless told otherwise, to stderr (spec 10.1)."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"ingest.{log_path}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handlers = [logging.FileHandler(log_path, encoding="utf-8")]
    if console:
        handlers.append(logging.StreamHandler(sys.stderr))
    for handler in handlers:
        handler.setFormatter(_Formatter())
        logger.addHandler(handler)
    return logger


# Peak memory per MB (MiB) of input. Measured: 39 at 100,000 records, 29 at 1,000,000; rounded up to stay safe.
MEMORY_PER_INPUT_MB = 40


def estimate_peak_mb(input_mb: float) -> float:
    return input_mb * MEMORY_PER_INPUT_MB


class MemoryGuard:
    """Spec 10.3: warn once above the warning share of total memory, stop above the stop share."""

    def __init__(self, warn_pct: float, stop_pct: float, total_mb: float | None):
        self.warn_pct, self.stop_pct, self.total_mb = warn_pct, stop_pct, total_mb
        self._warned = self._unknown_reported = False

    def preflight(self, input_mb: float) -> list[str]:
        """Before reading: stop at once when the estimated peak is above the stop share of total memory."""
        if self.total_mb is None:
            return self.check("read")
        estimate = estimate_peak_mb(input_mb)
        limit = self.total_mb * self.stop_pct / 100
        if estimate > limit:
            from ingest.errors import RunError
            raise RunError("MEMORY_LIMIT",
                           f"Input of {input_mb:.0f} MB needs about {estimate:.0f} MB of memory, above the limit of "
                           f"{limit:.0f} MB ({self.stop_pct:g}% of total memory); the file was not read", "read")
        return []

    def check(self, stage: str) -> list[str]:
        if self.total_mb is None:
            if self._unknown_reported:
                return []
            self._unknown_reported = True
            return ["MEMORY_TOTAL_UNKNOWN"]
        peak = peak_memory_mb()
        if peak is None:
            return []
        share = 100 * peak / self.total_mb
        if share > self.stop_pct:
            from ingest.errors import RunError
            raise RunError("MEMORY_LIMIT", f"Memory use passed {self.stop_pct:g}% of total memory; run stopped", stage)
        if share > self.warn_pct and not self._warned:
            self._warned = True
            return ["MEMORY_WARNING"]
        return []
