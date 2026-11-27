"""Pruebas unitarias para el comprobador estricto de paquetes."""
from types import SimpleNamespace

from core.repositories.package_checker import (
    check_package_exists,
    invalid_package_names,
)


def test_invalid_package_names():
    assert invalid_package_names("valid-pkg, another_pkg") == []
    assert invalid_package_names("bad;pkg, space pkg") == ["bad;pkg"]


def test_check_package_exists_rejects_empty_and_invalid():
    assert check_package_exists("") is False
    assert check_package_exists("bad;name") is False


def test_check_package_exists_fails_closed_without_dnf(monkeypatch):
    monkeypatch.setattr("core.repositories.package_checker.shutil.which", lambda _name: None)
    assert check_package_exists("kernel") is False


def test_check_package_exists_accepts_exact_repoquery_result(monkeypatch):
    monkeypatch.setattr("core.repositories.package_checker.shutil.which", lambda name: "/usr/bin/dnf5" if name == "dnf5" else None)
    monkeypatch.setattr(
        "core.repositories.package_checker.subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="kernel\n", stderr=""),
    )
    assert check_package_exists("kernel") is True


def test_check_package_exists_rejects_nonmatching_result(monkeypatch):
    monkeypatch.setattr("core.repositories.package_checker.shutil.which", lambda _name: "/usr/bin/dnf")
    monkeypatch.setattr(
        "core.repositories.package_checker.subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="kernel-core\n", stderr=""),
    )
    assert check_package_exists("kernel") is False


def test_check_package_exists_rejects_dnf_error(monkeypatch):
    monkeypatch.setattr("core.repositories.package_checker.shutil.which", lambda _name: "/usr/bin/dnf")
    monkeypatch.setattr(
        "core.repositories.package_checker.subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="repo unavailable"),
    )
    assert check_package_exists("kernel") is False
