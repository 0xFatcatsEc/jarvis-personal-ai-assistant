"""Assemble the Windows x64 Foundation bundle using the provisioned MSI runtime."""
import argparse
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

from pip._vendor.packaging.tags import sys_tags
from pip._vendor.packaging.utils import parse_wheel_filename

from provision_assets import inventory, provision, LOCK, RELEASE

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build(output: Path, cache: Path) -> None:
    root = Path(os.environ["LOCALAPPDATA"]) / "StylusJarvis"
    runtime = root / "runtime"
    if Path(sys.executable) != runtime / "python/python.exe" or platform.python_version() != "3.12.13":
        raise ValueError("Use the dedicated CPython 3.12.13 executable.")
    if output.exists() or output.is_relative_to(runtime) or output.is_relative_to(cache):
        raise ValueError("Choose a fresh bundle path outside the runtime and wheel cache.")
    pins = json.loads(LOCK.read_bytes())
    assets = root / "assets/m0-v1"
    inventory(assets, pins["assets"])
    release = tomllib.loads(RELEASE.read_text("utf-8"))
    packages = tomllib.loads((REPO / "uv.lock").read_text("utf-8"))["package"]
    tags = list(sys_tags())
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix="bundle-build-") as work:
        stage = Path(work) / "bundle"
        wheels = stage / "wheels"
        wheels.mkdir(parents=True)
        for pkg in packages:
            if pkg["name"] == "stylus-jarvis":
                continue
            candidates = []
            for wheel in pkg["wheels"]:
                filename = wheel["url"].rsplit("/", 1)[1]
                compatible = parse_wheel_filename(filename)[3].intersection(tags)
                if compatible:
                    candidates.append((min(tags.index(tag) for tag in compatible), filename, wheel))
            _, filename, wheel = min(candidates, key=lambda item: item[:2])
            provision(cache, dict(path=filename, url=wheel["url"], size=wheel["size"],
                                  sha256=wheel["hash"].removeprefix("sha256:")))
            shutil.copyfile(cache / filename, wheels / filename)
        source = Path(work) / "source"
        source.mkdir()
        shutil.copyfile(REPO / "pyproject.toml", source / "pyproject.toml")
        shutil.copytree(REPO / "src/stylus_jarvis", source / "src/stylus_jarvis",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        constraint = Path(work) / "build-constraints.txt"
        constraint.write_text("setuptools==84.2.1\n", encoding="ascii")
        subprocess.run(["uv", "build", "--wheel", "--python", sys.executable, "--build-constraint",
                        constraint.name, "--out-dir", str(wheels), str(source)], cwd=work, check=True)
        with zipfile.ZipFile(stage / "runtime.zip", "w", allowZip64=True) as archive:
            for name in ("python", "ollama"):
                for file in sorted((runtime / name).rglob("*")):
                    if file.is_file() and "__pycache__" not in file.parts and file.suffix != ".pyc":
                        archive.write(file, file.relative_to(runtime))
        with zipfile.ZipFile(stage / "assets.zip", "w", allowZip64=True) as archive:
            for asset in pins["assets"]:
                archive.write(assets / asset["path"], asset["path"])
        for name in ("install-release.ps1", "launch-release.ps1", "m0-assets.json"):
            shutil.copyfile(HERE / name, stage / name)
        shutil.copyfile(REPO / "uv.lock", stage / "uv.lock")
        sql = sorted((RELEASE.parent / "storage/migrations").glob("*.sql"))
        manifest = dict(build=release["build"], python=platform.python_version(), sqlite=sqlite3.sqlite_version,
                        schema=int(sql[-1].name.split("_")[0]), migrations={p.name: digest(p) for p in sql},
                        ollama=pins["ollama_version"], ollama_exe_sha256=digest(runtime / "ollama/ollama.exe"),
                        model=release["model"], model_digest=release["digest"],
                        files={p.relative_to(stage).as_posix(): digest(p) for p in sorted(stage.rglob("*"))
                               if p.is_file()})
        (stage / "bundle.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        stage.rename(output)
    print("Bundle manifest SHA-256:", digest(output / "bundle.json"), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--wheel-cache", type=Path, required=True)
    args = parser.parse_args()
    build(args.output.resolve(), args.wheel_cache.resolve())
