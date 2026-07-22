"""Terminal mouse-tracking reset emitted around `up`/`down` (kills the SGR-report pollution)."""

import io

from citadel import _terminal


class _FakeTTY(io.StringIO):
    def __init__(self, is_tty: bool):
        super().__init__()
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def test_reset_disables_motion_tracking_on_a_tty(monkeypatch):
    out = _FakeTTY(is_tty=True)
    monkeypatch.setattr(_terminal.sys, "stdout", out)

    _terminal.reset_terminal_input_modes()

    written = out.getvalue()
    assert "\033[?1003l" in written  # the any-motion flood source
    assert "\033[?1006l" in written  # SGR extended coords
    assert "\033[?25h" in written    # cursor restored


def test_reset_is_noop_when_stdout_is_not_a_tty(monkeypatch):
    out = _FakeTTY(is_tty=False)
    monkeypatch.setattr(_terminal.sys, "stdout", out)

    _terminal.reset_terminal_input_modes()

    assert out.getvalue() == ""


def test_reset_swallows_io_errors(monkeypatch):
    class _Broken(_FakeTTY):
        def write(self, _s):
            raise OSError("closed pipe")

    monkeypatch.setattr(_terminal.sys, "stdout", _Broken(is_tty=True))

    _terminal.reset_terminal_input_modes()  # must not raise
