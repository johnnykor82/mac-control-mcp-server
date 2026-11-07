"""BF28 latest release selection never trusts stale beta.12 or downgrades."""
import hashlib

import pytest

from scripts import setup_chatbridge_dependency as dep


def release(number, *, repo="johnnykor82/chatbridge", draft=False):
    tag = f"v0.2.0-beta.{number}"
    prefix = f"https://github.com/{repo}/releases/download/{tag}/"
    return {
        "tag_name": tag, "draft": draft, "prerelease": True,
        "assets": [
            {"name": f"chatbridge_gateway-0.2.0b{number}.tar.gz",
             "browser_download_url": prefix + f"chatbridge_gateway-0.2.0b{number}.tar.gz"},
            {"name": "SHA256SUMS",
             "browser_download_url": prefix + "SHA256SUMS"},
        ],
    }


def test_selects_highest_numeric_beta_not_first_and_rejects_draft():
    latest = dep.select_latest_release([
        release(12), release(9), release(21, draft=True), release(20),
        release(19),
    ])
    assert latest["version"] == "0.2.0b20"
    assert latest["directory"] == "chatbridge_gateway-0.2.0b20"
    assert latest["tag"] == "v0.2.0-beta.20"


def test_release_asset_urls_must_be_from_original_repo():
    with pytest.raises(RuntimeError):
        dep.select_latest_release([release(20, repo="attacker/unknown")])
    with pytest.raises(RuntimeError):
        dep.select_latest_release([release(20, draft=True)])


def test_manifest_requires_single_exact_checksum_for_correct_sdist():
    digest = hashlib.sha256(b"correct archive").hexdigest()
    name = "chatbridge_gateway-0.2.0b20.tar.gz"
    assert dep.checksum_for_asset(f"{digest}  {name}\n", name) == digest
    with pytest.raises(RuntimeError):
        dep.checksum_for_asset(f"{digest}  unexpected.tar.gz\n", name)
    with pytest.raises(RuntimeError):
        dep.checksum_for_asset(f"{digest}  {name}\n{digest}  {name}\n", name)


def test_no_downgrade_or_equal_version_restart():
    assert not dep.should_upgrade_chatbridge("0.2.0b20", "0.2.0b12")
    assert not dep.should_upgrade_chatbridge("0.2.0b20", "0.2.0b20")
    assert dep.should_upgrade_chatbridge("0.2.0b12", "0.2.0b20")
    with pytest.raises(RuntimeError):
        dep.should_upgrade_chatbridge("unknown", "0.2.0b20")


def _latest_source_archive(version="0.2.0b20"):
    import gzip
    import io
    import tarfile
    root = "chatbridge_gateway-" + version
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as tar:
        for name, content in [
            (root + "/pyproject.toml", f'name = "chatbridge-gateway"\nversion = "{version}"\n'),
            (root + "/scripts/installer.py", "print('safe installer')\n"),
        ]:
            body = content.encode()
            item = tarfile.TarInfo(name)
            item.size = len(body)
            item.mode = 0o644
            tar.addfile(item, io.BytesIO(body))
    return gzip.compress(data.getvalue())


def test_latest_archive_download_checks_digest_and_package_version(tmp_path, monkeypatch):
    import io
    data = _latest_source_archive()
    digest = hashlib.sha256(data).hexdigest()
    version = "0.2.0b20"
    url = f"https://github.com/johnnykor82/chatbridge/releases/download/v0.2.0-beta.20/chatbridge_gateway-{version}.tar.gz"
    class Response(io.BytesIO):
        def geturl(self):
            return url
    monkeypatch.setattr(dep.urllib.request, "urlopen", lambda *args, **kwargs: Response(data))
    spec = {"directory": "chatbridge_gateway-" + version,
            "asset_url": url, "sha256": digest, "version": version}
    result = dep.download_latest_source(tmp_path, spec)
    assert result.name == "chatbridge_gateway-0.2.0b20"
    assert 'version = "0.2.0b20"' in (result / "pyproject.toml").read_text()
    with pytest.raises(RuntimeError, match="SHA256"):
        dep.download_latest_source(tmp_path / "bad", {**spec, "sha256": "0"*64})


def test_installed_version_above_latest_never_calls_update(tmp_path, monkeypatch):
    source = tmp_path / "deps/chatbridge-source"
    source.mkdir(parents=True)
    (source / "pyproject.toml").write_text('version = "0.2.0b21"\n')
    monkeypatch.setattr(dep, "verify_managed_install", lambda _: None)
    monkeypatch.setattr(dep, "latest_published_release",
                        lambda: {"version": "0.2.0b20", "version_number": 20})
    monkeypatch.setattr(dep, "download_latest_source",
                        lambda *_: pytest.fail("Never download old release"))
    assert dep.upgrade_managed(tmp_path)["status"] == "current"


def test_existing_managed_source_cannot_be_reused_for_newer_verified_release(tmp_path, monkeypatch):
    old = tmp_path / "deps/chatbridge-source"
    old.mkdir(parents=True)
    (old / "scripts").mkdir()
    (old / "scripts/installer.py").write_text("print('old')\n")
    (old / "pyproject.toml").write_text('version = "0.2.0b12"\n')
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "pyproject.toml").write_text('version = "0.2.0b20"\n')
    monkeypatch.setattr(dep, "install",
                        lambda *_args, **_kwargs: pytest.fail("Never install stale source"))
    with pytest.raises(RuntimeError, match="Existing.*ChatBridge.*source"):
        dep._install_verified_source(candidate, dep.DEFAULT_URL, tmp_path)
    assert '0.2.0b12' in (old / "pyproject.toml").read_text()


def test_newer_runtime_blocks_upgrade_from_stale_source(tmp_path, monkeypatch):
    source = tmp_path / "deps/chatbridge-source"
    source.mkdir(parents=True)
    (source / "pyproject.toml").write_text('version = "0.2.0b11"\n')
    monkeypatch.setattr(dep, "verify_managed_install", lambda _: None)
    monkeypatch.setattr(dep, "latest_published_release",
                        lambda: {"version": "0.2.0b20", "version_number": 20})
    monkeypatch.setattr(dep, "managed_installed_runtime_version",
                        lambda _: "0.2.0b21", raising=False)
    monkeypatch.setattr(dep, "download_latest_source",
                        lambda *_: pytest.fail("Do not downgrade running ChatBridge"))
    assert dep.upgrade_managed(tmp_path)["status"] == "current"


def test_clean_runner_without_launchagents_has_no_runtime_version(tmp_path, monkeypatch):
    """CI fixture has no owner service; upgrade_managed's owner guard stays strict."""
    monkeypatch.setattr(dep.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(dep, "managed_service_label",
                        lambda *_: pytest.fail("No service, so don't inspect ownership"))
    assert dep.managed_installed_runtime_version(tmp_path / "MacControlMCP") is None
