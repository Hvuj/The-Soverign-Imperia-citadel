"""Terminal-state hygiene around launching/stopping the Claude Code TUI.

The VS Code integrated terminal (and most emulators) are *persistent*: a Claude Code
session that exits without cleanly disabling mouse-reporting leaves the terminal in
tracking mode. The next shell prompt then echoes every mouse move as literal text
(`ESC[<35;COL;ROWM` …) — the "symbols every couple of seconds" the operator sees.
These are local terminal reports, not program output and not API traffic; clearing the
modes stops the shell echoing them. Every sequence is a no-op if already disabled.
"""

import sys

_RESET = (
    "\033[?1000l"  # normal button tracking
    "\033[?1002l"  # button-event (drag) tracking
    "\033[?1003l"  # any-event (motion) tracking — the flood source
    "\033[?1005l"  # UTF-8 extended coordinates
    "\033[?1006l"  # SGR extended coordinates
    "\033[?1015l"  # urxvt extended coordinates
    "\033[?2004l"  # bracketed paste off
    "\033[?25h"    # show cursor
)


def reset_terminal_input_modes() -> None:
    """Disable mouse-reporting so the shell stops echoing motion reports as text.

    No-op unless stdout is a real terminal, so it never corrupts piped or redirected output.
    """
    out = sys.stdout
    try:
        if not out.isatty():
            return
        out.write(_RESET)
        out.flush()
    except (OSError, ValueError):
        pass
