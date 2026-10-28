"""Small, offline checks for the portable runtime installer."""

import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "tools/speech_runtime_installer.py"
spec = importlib.util.spec_from_file_location("speech_runtime_installer", SCRIPT)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class SpeechRuntimeInstallerTests(unittest.TestCase):
    def test_repair_moves_virtualenv_home_to_new_plugin_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / ".speech-runtime"
            home = runtime / "python/cpython-3.10.21-windows-x86_64-none"
            home.mkdir(parents=True)
            (home / "python.exe").touch()
            (runtime / "env").mkdir()
            cfg = runtime / "env/pyvenv.cfg"
            cfg.write_text("home = C:\\OldPC\\python\nversion_info = 3.10\n", encoding="utf-8")
            installer.repair_venv(runtime)
            self.assertIn(f"home = {home}", cfg.read_text(encoding="utf-8"))
            self.assertIn("version_info = 3.10", cfg.read_text(encoding="utf-8"))

    def test_zip_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "bad.zip"
            with zipfile.ZipFile(archive, "w") as out:
                out.writestr("../escape.txt", "bad")
            with self.assertRaises(RuntimeError):
                installer.unpack_zip(archive, root / "destination")
            self.assertFalse((root / "escape.txt").exists())

    def test_zip_extracts_safe_package(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "good.zip"
            with zipfile.ZipFile(archive, "w") as out:
                out.writestr("models/quality/silero_vad.onnx", b"model")
            installer.unpack_zip(archive, root / "destination")
            self.assertEqual((root / "destination/models/quality/silero_vad.onnx").read_bytes(), b"model")

    def test_model_lock_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            for name in installer.REQUIRED:
                target = runtime / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            (runtime / f"models/{installer.MODEL_NAME}/hutx-model-lock.json").write_text(
                json.dumps({**installer.LOCK, "model_revision": "wrong"}), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "model_revision"):
                installer.check_files(runtime)

    def test_package_and_install_rebase_without_online_download(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "source/.speech-runtime"
            destination_root = base / "target"
            destination_root.mkdir()
            for name in installer.REQUIRED:
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            home = source / "python/cpython-3.10.21-windows-x86_64-none"
            home.mkdir(parents=True)
            (home / "python.exe").touch()
            (source / "env/pyvenv.cfg").write_text("home = C:\\PreviousPC\\python\n", encoding="utf-8")
            (source / f"models/{installer.MODEL_NAME}/hutx-model-lock.json").write_text(
                json.dumps(installer.LOCK), encoding="utf-8")
            (source / "environment-ready.json").write_text("{}", encoding="utf-8")
            bundle = base / "runtime.zip"
            with patch.object(installer, "RUNTIME", source):
                installer.package(bundle)
            checksum_file = bundle.with_name(bundle.name + ".sha256")
            checksum = checksum_file.read_text(encoding="ascii")
            checksum_file.write_text("0" * 64 + "  runtime.zip\n", encoding="ascii")
            with patch.object(installer, "ROOT", destination_root), \
                 patch.object(installer, "RUNTIME", destination_root / ".speech-runtime"):
                with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                    installer.install_bundle(bundle)
            checksum_file.write_text(checksum, encoding="ascii")
            with patch.object(installer, "ROOT", destination_root), \
                 patch.object(installer, "RUNTIME", destination_root / ".speech-runtime"), \
                 patch.object(installer, "check"):
                installer.install_bundle(bundle)
            rebased = destination_root / ".speech-runtime"
            self.assertIn(f"home = {rebased / 'python/cpython-3.10.21-windows-x86_64-none'}",
                          (rebased / "env/pyvenv.cfg").read_text(encoding="utf-8"))
            self.assertFalse((destination_root / ".speech-runtime.installing").exists())


if __name__ == "__main__":
    unittest.main()
