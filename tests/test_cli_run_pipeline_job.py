from __future__ import annotations

from pathlib import Path

import pytest

from ifc_book_prototype import cli


def test_run_pipeline_job_requires_ifc_or_bundle(tmp_path: Path):
    with pytest.raises(ValueError, match="Either an IFC path or --bundle is required."):
        cli.run_pipeline_job(output_dir=tmp_path / "out")


def test_run_pipeline_job_rejects_ifc_and_bundle_together(tmp_path: Path):
    ifc_path = tmp_path / "model.ifc"
    bundle_dir = tmp_path / "bundle"
    ifc_path.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
    bundle_dir.mkdir()
    with pytest.raises(ValueError, match="Specify either an IFC path or --bundle, not both."):
        cli.run_pipeline_job(
            output_dir=tmp_path / "out",
            ifc_path=ifc_path,
            bundle_dir=bundle_dir,
        )


def test_run_pipeline_job_dispatches_to_pipeline(monkeypatch, tmp_path: Path):
    ifc_path = tmp_path / "model.ifc"
    out_dir = tmp_path / "out"
    ifc_path.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")

    calls: dict[str, object] = {}
    profile_marker = object()
    manifest_marker = object()

    class _FakePipeline:
        def __init__(self, profile):
            calls["profile"] = profile

        def run(self, *, ifc_path: Path, output_dir: Path):
            calls["ifc_path"] = ifc_path
            calls["output_dir"] = output_dir
            return manifest_marker

    def _fake_load_style_profile(profile_path: str | None):
        calls["profile_path"] = profile_path
        return profile_marker

    monkeypatch.setattr(cli, "PrototypePipeline", _FakePipeline)
    monkeypatch.setattr(cli, "load_style_profile", _fake_load_style_profile)

    manifest = cli.run_pipeline_job(
        output_dir=out_dir,
        profile_path="custom_profile.json",
        ifc_path=ifc_path,
    )

    assert manifest is manifest_marker
    assert calls == {
        "profile_path": "custom_profile.json",
        "profile": profile_marker,
        "ifc_path": ifc_path,
        "output_dir": out_dir,
    }


def test_run_pipeline_job_dispatches_to_bundle_replay(monkeypatch, tmp_path: Path):
    bundle_dir = tmp_path / "bundle"
    out_dir = tmp_path / "out"
    bundle_dir.mkdir()

    calls: dict[str, object] = {}
    profile_marker = object()
    manifest_marker = object()

    def _fake_load_style_profile(profile_path: str | None):
        calls["profile_path"] = profile_path
        return profile_marker

    def _fake_replay_bundle(*, bundle_dir: Path, output_dir: Path, profile):
        calls["bundle_dir"] = bundle_dir
        calls["output_dir"] = output_dir
        calls["profile"] = profile
        return manifest_marker

    monkeypatch.setattr(cli, "load_style_profile", _fake_load_style_profile)
    monkeypatch.setattr(cli, "replay_bundle", _fake_replay_bundle)

    manifest = cli.run_pipeline_job(
        output_dir=out_dir,
        profile_path=None,
        bundle_dir=bundle_dir,
    )

    assert manifest is manifest_marker
    assert calls == {
        "profile_path": None,
        "bundle_dir": bundle_dir,
        "output_dir": out_dir,
        "profile": profile_marker,
    }

