from click.testing import CliRunner

from infra_atlas.cli import _find_repo_root, cli


def test_find_repo_root_falls_back_for_flat_image_layout(tmp_path):
    app_root = tmp_path / "app"
    module_path = app_root / "infra_atlas" / "cli.py"
    module_path.parent.mkdir(parents=True)
    module_path.touch()

    assert _find_repo_root(module_path, fallback=app_root) == app_root


def test_cli_help_is_importable():
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
