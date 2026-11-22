"""Provision or recheck the Phase 1 asset inventory. Verify mode needs no network."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
from typing import TypedDict


class Asset(TypedDict):
    path: str
    size: int
    sha256: str
    url: str


HERE = Path(__file__).resolve().parent
LOCK = HERE / "m0-assets.json"
RELEASE = HERE.parents[1] / "src/stylus_jarvis/release-manifest.toml"
MODEL = "ollama/models/manifests/registry.ollama.ai/library/qwen3/4b"


def destination(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or path == root.resolve():
        raise ValueError(f"Asset path outside staging directory: {name}")
    return path


def verify(path: Path, asset: Asset) -> None:
    if path.stat().st_size != asset["size"]:
        raise ValueError(f"Size mismatch: {asset['path']}")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != asset["sha256"]:
        raise ValueError(f"Digest mismatch: {asset['path']}")


def provision(root: Path, asset: Asset) -> None:
    path = destination(root, asset["path"])
    if path.exists():
        verify(path, asset)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".partial", delete=False) as out:
        temporary = Path(out.name)
    try:
        subprocess.run(["curl.exe", "--fail", "--silent", "--show-error", "--location",
                        "--proto", "=https", "--proto-redir", "=https", "--connect-timeout", "30",
                        "--speed-limit", "1024", "--speed-time", "90", "--retry", "3",
                        "--retry-all-errors", "--output", str(temporary), asset["url"]], check=True)
        verify(temporary, asset)
        temporary.replace(path)
        print(f"Verified {asset['path']}", flush=True)
    finally:
        temporary.unlink(missing_ok=True)


def inventory(root: Path, assets: list[Asset]) -> dict[str, object]:
    for asset in assets:
        verify(destination(root, asset["path"]), asset)
    release = tomllib.loads(RELEASE.read_text(encoding="utf-8"))
    indexed = {asset["path"]: asset for asset in assets}
    if indexed[MODEL]["sha256"] != release["digest"]:
        raise ValueError("Qwen digest differs from the runtime release manifest")
    manifest = json.loads(destination(root, MODEL).read_bytes())
    for layer in [manifest["config"], *manifest["layers"]]:
        algorithm, digest = layer["digest"].split(":")
        blob = indexed.get(f"ollama/models/blobs/sha256-{digest}")
        if algorithm != "sha256" or not blob or (blob["size"], blob["sha256"]) != (layer["size"], digest):
            raise ValueError("Missing or mismatched Qwen blob in inventory")
    return {"backlog": "1.1.2.1", "verified_at_utc": datetime.now(UTC).isoformat(),
            "file_count": len(assets), "total_bytes": sum(a["size"] for a in assets),
            "inventory_sha256": hashlib.sha256(LOCK.read_bytes()).hexdigest(),
            "verified": [{"path": a["path"], "sha256": a["sha256"], "bytes": a["size"]} for a in assets]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["provision", "verify"])
    parser.add_argument("--root", type=Path, default=Path(os.environ["LOCALAPPDATA"]) / "StylusJarvis/assets/m0-v1")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    assets: list[Asset] = json.loads(LOCK.read_text(encoding="utf-8"))["assets"]
    if args.action == "provision":
        args.root.mkdir(parents=True, exist_ok=True)
        missing = sum(a["size"] for a in assets if not destination(args.root, a["path"]).exists())
        if shutil.disk_usage(args.root).free < missing:
            raise OSError("Insufficient space for offline assets")
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda a: provision(args.root, a), assets))
    report = inventory(args.root, assets)
    if args.receipt:
        args.receipt.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {report['file_count']} files ({report['total_bytes']} bytes).")


if __name__ == "__main__":
    main()
