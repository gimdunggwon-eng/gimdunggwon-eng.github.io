from dataclasses import dataclass

import psutil
import time


@dataclass(frozen=True)
class SystemSnapshot:
    cpu_percent: float
    memory_percent: float
    memory_available_gb: float
    memory_used_gb: float
    memory_total_gb: float
    process_memory_mb: float
    uptime_seconds: int


class SystemMonitor:
    """Read-only CPU and memory sampler."""

    def sample(self) -> SystemSnapshot:
        memory = psutil.virtual_memory()
        gib = 1024 ** 3
        return SystemSnapshot(
            cpu_percent=psutil.cpu_percent(interval=None),
            memory_percent=memory.percent,
            memory_available_gb=memory.available / gib,
            memory_used_gb=memory.used / gib,
            memory_total_gb=memory.total / gib,
            process_memory_mb=psutil.Process().memory_info().rss / (1024 ** 2),
            uptime_seconds=max(0, int(time.time() - psutil.boot_time())),
        )
