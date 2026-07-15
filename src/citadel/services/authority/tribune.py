"""Tribune — sacrosanct process registry + stop-gate (masterplan §5.5).

Certain PIDs (the stop-gate watchdog, the operator's control channel) hold *sacrosanctitas*: no imperium's
enforcement may ever target them. The kill path checks this registry first and refuses, logging the attempt
as a constitutional violation. The Tribune holds no imperium of its own — it can only block, never command.
"""


class SacrosanctRegistry:
    def __init__(self) -> None:
        self._protected: set[int] = set()
        self._violations: list[int] = []

    def protect(self, pid: int) -> None:
        self._protected.add(pid)

    def unprotect(self, pid: int) -> None:
        self._protected.discard(pid)

    def is_sacrosanct(self, pid: int) -> bool:
        return pid in self._protected

    def may_kill(self, pid: int) -> bool:
        """False for a sacrosanct PID — and the refused attempt is recorded as a constitutional violation."""
        if pid in self._protected:
            self._violations.append(pid)
            return False
        return True

    @property
    def violations(self) -> list[int]:
        return list(self._violations)
