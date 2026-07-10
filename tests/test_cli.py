"""tests/test_cli.py — CLI parser smoke tests."""
import pytest

from citadel.cli import _build_parser


def test_parser_builds():
    parser = _build_parser()
    assert parser is not None


def test_init_defaults_workspace_to_dot():
    parser = _build_parser()
    args = parser.parse_args(["init"])
    assert args.workspace == "."
    assert args.branch is None
    assert args.force is False


def test_init_explicit_workspace():
    parser = _build_parser()
    args = parser.parse_args(["init", "/tmp/myrepo"])
    assert args.workspace == "/tmp/myrepo"


def test_up_parses():
    parser = _build_parser()
    args, _ = parser.parse_known_args(["up"])
    assert args.command == "up"
    assert args.dry_run is False
    assert args.no_ui is False
    assert args.workspace is None


def test_up_dry_run():
    parser = _build_parser()
    args, _ = parser.parse_known_args(["up", "--dry-run", "--no-ui"])
    assert args.dry_run is True
    assert args.no_ui is True


def test_up_workspace_flag():
    parser = _build_parser()
    args, _ = parser.parse_known_args(["up", "--workspace", "/tmp/ws"])
    assert args.workspace == "/tmp/ws"


def test_up_forwards_unknown_args_to_claude():
    parser = _build_parser()
    args, unknown = parser.parse_known_args(["up", "--some-claude-flag", "x"])
    assert args.command == "up"
    assert unknown == ["--some-claude-flag", "x"]


def test_down_parses():
    parser = _build_parser()
    args = parser.parse_args(["down"])
    assert args.command == "down"
    assert args.workspace is None


def test_help_includes_up_and_down(capsys):
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    captured = capsys.readouterr()
    assert "up" in captured.out
    assert "down" in captured.out


def test_help_includes_init(capsys):
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    captured = capsys.readouterr()
    assert "init" in captured.out


def test_run_parses_task_and_defaults():
    parser = _build_parser()
    args = parser.parse_args(["run", "fix", "the", "thing"])
    assert args.task == ["fix", "the", "thing"]
    assert args.max_workers == 4
    assert args.company is None
    assert args.dry_run is False
    assert args.no_ui is False
    assert args.autonomous is False
    assert args.smoke is False
    assert args.no_dashboard is False
    assert args.permission_mode is None


def test_run_flags_parse():
    parser = _build_parser()
    args = parser.parse_args([
        "run", "do it",
        "--max-workers", "6", "--company", "acme", "--dry-run", "--no-ui",
        "--autonomous", "--smoke", "--no-dashboard", "--permission-mode", "plan",
    ])
    assert args.task == ["do it"]
    assert args.max_workers == 6
    assert args.company == "acme"
    assert args.dry_run is True
    assert args.no_ui is True
    assert args.autonomous is True
    assert args.smoke is True
    assert args.no_dashboard is True
    assert args.permission_mode == "plan"


def test_run_requires_a_task():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run"])


def test_help_includes_run(capsys):
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    captured = capsys.readouterr()
    assert "run" in captured.out
