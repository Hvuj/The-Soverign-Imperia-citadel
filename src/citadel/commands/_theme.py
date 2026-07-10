"""_theme.py â€” Cinematic themed output for `citadel init` and `citadel up`."""

import time

_INIT_LINES = [
    ">> [INIT] Booting Citadel core engine... OK",
    ">> [INIT] Scanning global sub-networks... OK",
    ">> [INIT] Security firewalls detected: 14 active.",
    ">> [WARN] Systems isolated. Awaiting deployment configuration.",
]

_BANNER_LINES = [
    ">> [CONNECTING] Allocating socket mesh...",
    ">> [NODES] 4,192 local hosts synchronized.",
    ">> [STATE] Merging independent consciousness streams...",
    ">> [STATUS] Convergence complete.",
    ">>",
    '>> "We are many."',
]


def _print_lines(lines: list[str], delay: float = 0.06) -> None:
    for line in lines:
        print(line, flush=True)
        time.sleep(delay)
    print()


def print_init_banner() -> None:
    """Print the `citadel init` cinematic banner."""
    _print_lines(_INIT_LINES)


def print_up_banner() -> None:
    """Print the `citadel up` cinematic banner."""
    _print_lines(_BANNER_LINES)
