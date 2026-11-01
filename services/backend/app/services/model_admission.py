"""Non-waiting permits shared by Linux workers on one local filesystem.

The directory is a stable namespace: never delete/replace it or its slot files
while workers run. All workers must use the same capacity. Separate containers
must mount the same local directory; network filesystems are not supported.
The kernel releases a permit on process exit; no expiring lease can admit a
replacement while its predecessor is still executing.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
from types import TracebackType


class AdmissionBusyError(Exception):
    """All permits are occupied; no work was queued."""


class Permit:
    def __init__(self, descriptor: int) -> None:
        self._descriptor: int | None = descriptor

    def close(self) -> None:
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is not None:
            os.close(descriptor)

    def __enter__(self) -> Permit:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class FileAdmission:
    def __init__(self, directory: Path, capacity: int) -> None:
        if not 1 <= capacity <= 64:
            raise ValueError("Model capacity must be between 1 and 64")
        self._directory = directory
        self._capacity = capacity

    def acquire(self) -> Permit:
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        for slot in range(self._capacity):
            descriptor = os.open(
                self._directory / f"slot-{slot}.lock",
                os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
            )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(descriptor)
                continue
            except BaseException:
                os.close(descriptor)
                raise
            return Permit(descriptor)
        raise AdmissionBusyError
