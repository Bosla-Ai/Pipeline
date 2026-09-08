"""Exercise the deployment copy, including the src/cache regression."""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def test_deploy_copies_source_cache_but_preserves_runtime_cache(tmp_path: Path) -> None:
    rsync = shutil.which("rsync")
    if rsync is None:
        pytest.skip("rsync is required; this regression runs on the Linux CI runner")

    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load(
        (root / ".github/workflows/deploy-pipeline.yml").read_text(encoding="utf-8")
    )
    sync_step = next(
        step for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("name") == "Sync code to service directory"
    )
    command = shlex.split(sync_step["run"].replace("\\\n", " "))
    assert command[0] == "rsync"

    source = tmp_path / "checkout"
    destination = tmp_path / "service"
    (source / "src/cache/__pycache__").mkdir(parents=True)
    (source / "src/__init__.py").write_text("", encoding="utf-8")
    for name in ("__init__.py", "keys.py", "pipeline_cache.py"):
        shutil.copy2(root / "src/cache" / name, source / "src/cache" / name)
    (source / "src/cache/__pycache__/ignored.pyc").write_bytes(b"not source")
    (source / "cache").mkdir()
    (source / "cache/do-not-deploy.json").write_text("{}", encoding="utf-8")
    (source / ".env").write_text("TEST_ONLY=source\n", encoding="utf-8")

    (destination / "cache").mkdir(parents=True)
    (destination / "cache/keep.json").write_text("runtime data", encoding="utf-8")
    (destination / ".env").write_text("TEST_ONLY=server\n", encoding="utf-8")
    (destination / "src/cache").mkdir(parents=True)
    (destination / "src/cache/obsolete.py").write_text("old code", encoding="utf-8")

    # Use the workflow's actual flags, replacing only the two sandbox paths.
    subprocess.run(
        [rsync, *command[1:-2], f"{source}/", f"{destination}/"],
        check=True, capture_output=True, text=True,
    )
    for name in ("__init__.py", "keys.py", "pipeline_cache.py"):
        assert (destination / "src/cache" / name).read_bytes() == (
            source / "src/cache" / name
        ).read_bytes()
    assert not (destination / "src/cache/obsolete.py").exists()
    assert not (destination / "src/cache/__pycache__").exists()
    assert (destination / "cache/keep.json").read_text() == "runtime data"
    assert not (destination / "cache/do-not-deploy.json").exists()
    assert (destination / ".env").read_text() == "TEST_ONLY=server\n"
    subprocess.run(
        [sys.executable, "-c",
         "from importlib.util import find_spec; "
         "assert find_spec('src.cache.pipeline_cache') is not None; "
         "assert find_spec('src.cache.keys') is not None"],
        cwd=destination, check=True, capture_output=True, text=True,
    )
