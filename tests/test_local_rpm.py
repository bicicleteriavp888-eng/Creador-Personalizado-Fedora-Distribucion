"""Pruebas de la inspección y política común de RPM locales."""
import subprocess

import pytest

from core.software import local_rpm
from core.software.local_rpm import LocalRPMError, inspect_local_rpm, inspect_local_rpms


def _verified(**overrides):
    value = {
        "signed": True, "trusted": True, "unsigned": False,
        "digest_ok": True, "verified": True, "error": "",
    }
    value.update(overrides)
    return value


def test_inspect_local_rpm_reads_metadata_after_trusted_verification(tmp_path, monkeypatch):
    rpm = tmp_path / "sample.rpm"
    rpm.write_bytes(b"rpm fixture")
    monkeypatch.setattr(local_rpm.shutil, "which", lambda _name: "/usr/bin/rpm")
    monkeypatch.setattr(local_rpm, "verify_rpm_signature", lambda _path: _verified())
    monkeypatch.setattr(
        local_rpm.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "sample\t1.2\t3.fc44\tx86_64\tSample package", ""),
    )
    result = inspect_local_rpm(rpm)
    assert result["name"] == "sample"
    assert result["version"] == "1.2"
    assert result["trusted"] is True


def test_unsigned_rpm_requires_explicit_permission(tmp_path, monkeypatch):
    rpm = tmp_path / "sample.rpm"
    rpm.write_bytes(b"rpm fixture")
    monkeypatch.setattr(local_rpm.shutil, "which", lambda _name: "/usr/bin/rpm")
    monkeypatch.setattr(local_rpm, "verify_rpm_signature", lambda _path: _verified(signed=False, trusted=False, unsigned=True, verified=False))
    with pytest.raises(LocalRPMError, match="sin firma"):
        inspect_local_rpm(rpm)


def test_invalid_digest_is_never_accepted_even_with_unsigned_permission(tmp_path, monkeypatch):
    rpm = tmp_path / "sample.rpm"
    rpm.write_bytes(b"rpm fixture")
    monkeypatch.setattr(local_rpm.shutil, "which", lambda _name: "/usr/bin/rpm")
    monkeypatch.setattr(local_rpm, "verify_rpm_signature", lambda _path: _verified(digest_ok=False, unsigned=True, trusted=False))
    with pytest.raises(LocalRPMError, match="Digest"):
        inspect_local_rpm(rpm, allow_unsigned=True)


def test_inspect_local_rpms_rejects_duplicate_name_arch(tmp_path, monkeypatch):
    a, b = tmp_path / "a.rpm", tmp_path / "b.rpm"
    a.write_bytes(b"a"); b.write_bytes(b"b")
    monkeypatch.setattr(local_rpm, "inspect_local_rpm", lambda path, **kw: {
        "path": str(path), "name": "same", "arch": "x86_64"
    })
    with pytest.raises(LocalRPMError, match="más de un RPM"):
        inspect_local_rpms([a, b])
