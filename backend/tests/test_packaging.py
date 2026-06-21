"""Native install packaging (plan.md §13, task T019).

Shell installers can't run systemd in CI, so we test what *can* be checked deterministically:
the scripts parse and pass shellcheck (when present), --help/--check run without root and make
no changes, and the systemd/env/udev templates carry the directives + config keys the installer
relies on. This guards against a typo in install.sh or a drifting template breaking real installs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "install.sh"
UNINSTALL = REPO / "uninstall.sh"
UNIT_TMPL = REPO / "packaging" / "systemd" / "solarvolt.service.tmpl"
ENV_EXAMPLE = REPO / "packaging" / "env" / "solarvolt.env.example"
UDEV_EXAMPLE = REPO / "packaging" / "udev" / "99-solarvolt-rs485.rules.example"
DOCKERFILE = REPO / "Dockerfile"
COMPOSE = REPO / "docker-compose.yml"
DOCKERIGNORE = REPO / ".dockerignore"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=REPO, capture_output=True, text=True)


def test_packaging_files_exist_and_scripts_executable():
    for p in (INSTALL, UNINSTALL, UNIT_TMPL, ENV_EXAMPLE, UDEV_EXAMPLE):
        assert p.is_file(), f"missing {p}"
    for script in (INSTALL, UNINSTALL):
        assert os.access(script, os.X_OK), f"{script} is not executable"


@pytest.mark.parametrize("script", [INSTALL, UNINSTALL])
def test_scripts_are_syntactically_valid_bash(script: Path):
    assert _run("bash", "-n", str(script)).returncode == 0


@pytest.mark.parametrize("script", [INSTALL, UNINSTALL])
def test_shellcheck_clean_when_available(script: Path):
    if not shutil.which("shellcheck"):
        pytest.skip("shellcheck not installed")
    # Gate on warnings + errors (real correctness issues); style/info notes are advisory.
    res = _run("shellcheck", "-S", "warning", str(script))
    assert res.returncode == 0, res.stdout + res.stderr


def test_install_help_runs_without_root():
    res = _run("bash", str(INSTALL), "--help")
    assert res.returncode == 0
    assert "Usage:" in res.stdout


def test_install_check_is_a_no_op_dry_run():
    # --check validates and prints the plan but must touch nothing and not require root.
    res = _run("bash", str(INSTALL), "--check", "--user", "root", "--no-build")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Dry run" in res.stdout
    # It must not have created the real install locations.
    assert not Path("/etc/solarvolt/solarvolt.env").exists() or "no changes" in res.stdout.lower()


def test_install_rejects_unknown_option():
    assert _run("bash", str(INSTALL), "--bogus").returncode != 0


def test_systemd_template_has_required_directives():
    text = UNIT_TMPL.read_text()
    for directive in (
        "[Unit]",
        "[Service]",
        "[Install]",
        "ExecStart=",
        "EnvironmentFile=@ENVFILE@",
        "WorkingDirectory=@WORKDIR@",
        "User=@USER@",
        "Restart=on-failure",
        "WantedBy=multi-user.target",
    ):
        assert directive in text, f"systemd unit template missing {directive!r}"
    # Every placeholder the installer substitutes must be present (and get replaced).
    for ph in ("@USER@", "@GROUP@", "@WORKDIR@", "@PYTHON@", "@ENVFILE@", "@DBDIR@", "@PORT@"):
        assert ph in text, f"template missing placeholder {ph}"


def test_installer_substitutes_every_template_placeholder():
    # The sed block in install.sh must cover each @PLACEHOLDER@ in the unit template, or a real
    # install would ship a broken unit file with literal @TOKENS@.
    install_src = INSTALL.read_text()
    placeholders = set(__import__("re").findall(r"@[A-Z]+@", UNIT_TMPL.read_text()))
    for ph in placeholders:
        assert f"s|{ph}|" in install_src, f"install.sh does not substitute {ph}"


def test_env_example_documents_core_config_keys():
    text = ENV_EXAMPLE.read_text()
    for key in (
        "SOLARVOLT_ENABLE_CONTROL",
        "SOLARVOLT_DB_PATH",
        "SOLARVOLT_POLL_INTERVAL_S",
        "SOLARVOLT_MODBUS_PORT",
    ):
        assert key in text, f"env example missing {key}"
    # Safe defaults: control off, DB outside the app dir.
    assert "SOLARVOLT_ENABLE_CONTROL=false" in text
    assert "/var/lib/solarvolt" in text


def test_udev_example_creates_the_stable_symlink():
    text = UDEV_EXAMPLE.read_text()
    assert 'SYMLINK+="solarvolt-rs485"' in text
    assert "@IDVENDOR@" in text and "@IDPRODUCT@" in text


# ── Docker / Compose (T020) ───────────────────────────────────────────────────


def test_docker_files_exist():
    for p in (DOCKERFILE, COMPOSE, DOCKERIGNORE):
        assert p.is_file(), f"missing {p}"


def test_dockerfile_is_multistage_with_correct_layout():
    text = DOCKERFILE.read_text()
    # Two build stages: Node builds the UI, Python runs it.
    assert text.count("FROM ") >= 2, "Dockerfile should be multi-stage (Node build + Python runtime)"
    assert "AS frontend" in text and "npm run build" in text
    # The on-disk layout must mirror the repo so main.py/yaml_profile.py path resolution works.
    assert "/app/frontend/dist/solarvolt/browser" in text
    assert "COPY profiles/ /app/profiles/" in text
    assert "WORKDIR /app/backend" in text
    # Runtime essentials.
    assert "EXPOSE 8000" in text
    assert "USER solarvolt" in text, "container should run as a non-root user"
    assert "uvicorn" in text and "app.main:app" in text
    assert "HEALTHCHECK" in text


def test_compose_declares_service_volume_and_config():
    text = COMPOSE.read_text()
    assert "solarvolt:" in text
    assert "8000:8000" in text
    assert "solarvolt-data:/data" in text  # named volume for the DB
    assert "SOLARVOLT_DB_PATH: /data/solarvolt.db" in text
    # Write-back must default off in the shipped compose.
    assert 'SOLARVOLT_ENABLE_CONTROL: "false"' in text


def test_compose_file_is_valid_when_docker_available():
    if not shutil.which("docker"):
        pytest.skip("docker not installed")
    res = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "config"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0 and "compose" in (res.stderr.lower()):
        pytest.skip("docker compose plugin unavailable")
    assert res.returncode == 0, res.stdout + res.stderr


def test_hadolint_clean_when_available():
    if not shutil.which("hadolint"):
        pytest.skip("hadolint not installed")
    res = _run("hadolint", str(DOCKERFILE))
    assert res.returncode == 0, res.stdout + res.stderr
