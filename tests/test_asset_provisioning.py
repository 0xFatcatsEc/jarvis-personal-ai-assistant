"""Offline provisioning invariants; no model downloads in the unit suite."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "packaging/windows/provision_assets.py"
spec = importlib.util.spec_from_file_location("asset_provisioner", MODULE)
assert spec and spec.loader
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


class ProvisioningTests(unittest.TestCase):
    def test_local_verification_detects_corruption_truncation_and_absence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "voice"
            entry = {"size": 4, "sha256": hashlib.sha256(b"good").hexdigest(), "path": "voice"}
            with self.assertRaises(FileNotFoundError):
                assets.verify(path, entry)
            path.write_bytes(b"good")
            assets.verify(path, entry)
            for damaged in (b"baad", b"bad"):
                path.write_bytes(damaged)
                with self.assertRaises(ValueError):
                    assets.verify(path, entry)

    def test_failed_download_is_never_published(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.object(assets.subprocess, "run") as fetch:
            root = Path(temp)
            entry = {"size": 4, "sha256": hashlib.sha256(b"good").hexdigest(),
                     "path": "voice", "url": "https://example.invalid/voice"}
            with self.assertRaises(ValueError):
                assets.provision(root, entry)
            self.assertEqual(list(root.iterdir()), [])
            (root / "voice").write_bytes(b"good")
            assets.provision(root, entry)
            fetch.assert_called_once()

    def test_verification_rejects_incomplete_qwen_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / assets.MODEL
            path.parent.mkdir(parents=True)
            data = json.dumps({"config": {"size": 1, "digest": "sha256:"+"0"*64}, "layers":[]}).encode()
            path.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            release = root / "runtime.toml"
            release.write_text(f'digest = "{digest}"')
            entry = {"path": assets.MODEL, "size": len(data), "sha256": digest}
            with patch.object(assets, "RELEASE", release), self.assertRaisesRegex(ValueError, "blob"):
                assets.inventory(root, [entry])

    def test_inventory_pins_voice_companions_and_safe_paths(self) -> None:
        entries = json.loads(assets.LOCK.read_text())["assets"]
        names = [e["path"] for e in entries]
        self.assertEqual(len(names), len(set(names)))
        for name in ("piper/en_US-ljspeech-medium.onnx", "piper/en_US-ljspeech-medium.onnx.json",
                     "piper/MODEL_CARD", "whisper/ggml-base.bin", assets.MODEL):
            self.assertIn(name, names)
        for entry in entries:
            self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")
        with self.assertRaises(ValueError):
            assets.destination(Path.cwd(), "../escape")
