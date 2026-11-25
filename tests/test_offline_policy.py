"""Windows acceptance for 1.3.1.1. Synthetic endpoints never receive external traffic."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from pydantic import ValidationError

from stylus_jarvis.contracts.messages import ChatMessage, Code, Failure
from stylus_jarvis.inference.ollama import Ollama
from stylus_jarvis.runtime.diagnostics import Diagnostics, Event
from stylus_jarvis.runtime.offline import install_worker_policy, verify_application, verify_listener, whoami
from stylus_jarvis.settings import Manifest, Settings, check_local_route, load, save
from stylus_jarvis.storage.repositories import Repositories


def exercise_workers() -> None:
    # Audit hooks are process-wide and permanent. Exercise installation in a child.
    install_worker_policy()
    case = unittest.TestCase()
    with ThreadPoolExecutor(1) as worker:
        for operation, args in (
            (socket.getaddrinfo, ("telemetry.invalid", 443)),
            (socket.create_connection, (("127.0.0.1", 1),)),
            (socket.socket, (socket.AF_INET6, socket.SOCK_DGRAM)),
            (subprocess.run, ([sys.executable, "-V"],)),
        ):
            with case.assertRaises(Failure) as blocked:
                worker.submit(operation, *args).result()
            case.assertEqual(blocked.exception.code, Code.OFFLINE)
        case.assertIn(b"S-1-", worker.submit(whoami).result())
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        with case.assertRaises(Failure):
            udp.sendto(b"", ("192.0.2.1", 53))
    with socket.socket() as sock, case.assertRaises(Failure):
        sock.connect(("192.0.2.1", 443))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))


@unittest.skipUnless(os.name == "nt", "Windows offline runtime")
class OfflinePolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.manifest = Manifest(version=1, build="test", model="qwen3:4b", digest="a" * 64)

    def test_worker_socket_dns_and_process_policy(self) -> None:
        child = subprocess.run([sys.executable, "-B", __file__, "--workers"], capture_output=True, timeout=15)
        self.assertEqual(child.returncode, 0, child.stderr.decode(errors="replace"))

    async def test_worker_unc_and_mapped_roots_denied_before_access(self) -> None:
        import ctypes

        with (patch.object(Path, "lstat", side_effect=AssertionError("external filesystem access")),
              patch.object(Path, "resolve", side_effect=AssertionError("external path resolution"))):
            with self.assertRaises(Failure) as denied:
                await Repositories(Mock()).register("owner", Path(r"\\unreachable.invalid\projects"))
            self.assertEqual(denied.exception.code, Code.OFFLINE)
            for operation in (lambda path: load(path), lambda path: save(path, Settings())):
                with self.assertRaises(Failure) as config_blocked:
                    operation(Path(r"\\unreachable.invalid\settings"))
                self.assertEqual(config_blocked.exception.code, Code.OFFLINE)
            with patch.object(ctypes.windll.kernel32, "GetDriveTypeW", return_value=4), self.assertRaises(Failure):
                check_local_route(Path(r"Z:\mapped"))

    def test_diagnostics_stay_local_even_with_exporter_configured(self) -> None:
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://127.0.0.1:1", "SENTRY_DSN": "https://example.invalid"
        }), patch("socket.getaddrinfo") as dns, patch("socket.socket.connect") as connect:
            sink = Diagnostics(Path(root))
            sink.emit(Event.START)
            sink.close()
            self.assertFalse(sink.degraded)
            self.assertEqual(json.loads((Path(root) / "runtime.jsonl").read_text("utf-8"))["event"], "startup")
            inaccessible = Diagnostics(Path(r"\\unreachable.invalid\telemetry"))
            inaccessible.close()
            self.assertTrue(inaccessible.degraded)
            dns.assert_not_called()
            connect.assert_not_called()

    def test_numeric_loopback_and_offline_mode(self) -> None:
        for host in ("0.0.0.0", "::", "192.0.2.1", "2001:db8::1", "localhost", "127.0.0.1.example", "::1%3"):
            with self.subTest(host=host), self.assertRaises(ValidationError):
                Settings(host=host)
        self.assertEqual(Settings(host="::1").host, "::1")
        with self.assertRaises(ValidationError):
            Settings(offline=False)

    def test_serve_rejects_tray_updater_before_starting_any_process(self) -> None:
        # Simulate the layout of a GUI installation without modifying either
        # Ollama install. The guard must reject it before touching firewall state.
        policy = Path(__file__).resolve().parents[1] / "src/stylus_jarvis/runtime/offline-policy.ps1"
        script = r"""
            $ErrorActionPreference = 'Stop'
            function Get-Item($LiteralPath) { [pscustomobject]@{FullName=$LiteralPath} }
            function Get-ChildItem { }
            function Test-Path($LiteralPath) { (Split-Path -Leaf $LiteralPath) -eq 'ollama app.exe' }
            function Get-NetFirewallProfile { throw 'Unexpected firewall access' }
            $python = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'StylusJarvis\runtime\python\python.exe'
            try { & $env:STYLUS_TEST_POLICY -Mode Serve -PythonImage $python; exit 2 }
            catch { if ($_.Exception.Message -like '*without the tray application/updater*') { exit 0 }; throw }
        """
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
                                env={**os.environ, "STYLUS_TEST_POLICY": str(policy)}, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    async def test_unsafe_or_unverifiable_runtime_receives_no_chat(self) -> None:
        for cloud, entry, denied in (
            ({}, {}, False), ({"disabled": False}, {}, False), ({"disabled": "true"}, {}, False),
            ({"disabled": True}, {"remote_host": "https://cloud.invalid"}, False),
            ({"disabled": True}, {"remote_model": "remote"}, False), ({"disabled": True}, {}, True),
        ):
            with self.subTest(cloud=cloud, entry=entry, denied=denied):
                paths = []
                def handle(req: httpx.Request) -> httpx.Response:
                    paths.append(req.url.path)
                    self.assertEqual(req.method, "GET")
                    body = {"cloud": cloud} if req.url.path == "/api/status" else {"models": [{
                        "name": self.manifest.model, "digest": self.manifest.digest, **entry,
                    }]}
                    return httpx.Response(200, json=body)
                adapter = Ollama(Settings(), self.manifest, transport=httpx.MockTransport(handle))
                try:
                    with (patch("stylus_jarvis.inference.ollama.verify_listener",
                                side_effect=Failure(Code.OFFLINE) if denied else None),
                          self.assertRaises(Failure) as blocked):
                        _ = [part async for part in adapter.generate([ChatMessage("user", "private")])]
                    self.assertEqual(blocked.exception.code, Code.OFFLINE)
                    self.assertNotIn("/api/chat", paths)
                finally:
                    await adapter.close()

    async def test_ipv4_and_ipv6_chat_ignore_proxy_and_refuse_redirect(self) -> None:
        for host in ("127.0.0.1", "::1"):
            with self.subTest(host=host):
                paths = []
                async def server(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
                    try:
                        headers = (await reader.readuntil(b"\r\n\r\n")).decode("ascii").split("\r\n")
                        path = headers[0].split()[1]
                        paths.append(path)
                        length = next((int(h.split(":")[1]) for h in headers if h.lower().startswith("content-length:")), 0)
                        await reader.readexactly(length)
                        if path == "/api/chat":
                            response = b"HTTP/1.1 307 Redirect\r\nLocation: http://127.0.0.1:1/forbidden\r\nContent-Length: 0\r\n"
                        else:
                            body = json.dumps({"cloud": {"disabled": True}} if path == "/api/status" else {
                                "models": [{"name": self.manifest.model, "digest": self.manifest.digest}]
                            }).encode()
                            response = f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n".encode()
                        writer.write(response + b"Connection: close\r\n\r\n" + (b"" if path == "/api/chat" else body))
                        await writer.drain()
                    finally:
                        writer.close()
                        await writer.wait_closed()

                listener = await asyncio.start_server(server, host, 0)
                async with listener:
                    with (patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "NO_PROXY": "",
                                                  "OLLAMA_HOST": "http://cloud.invalid"}),
                          patch("stylus_jarvis.inference.ollama.verify_listener")):
                        adapter = Ollama(Settings(host=host, port=listener.sockets[0].getsockname()[1]), self.manifest)
                        try:
                            with self.assertRaises(Failure) as refused:
                                _ = [p async for p in adapter.generate([ChatMessage("user", "redirect test")])]
                            self.assertIsInstance(refused.exception.__cause__, httpx.HTTPStatusError)
                            self.assertEqual(paths, ["/api/status", "/api/tags", "/api/chat"])
                        finally:
                            await adapter.close()

    async def test_unmanaged_loopback_listener_fails_native_check(self) -> None:
        listener = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        async with listener:
            with self.assertRaises(Failure) as denied:
                await asyncio.to_thread(verify_listener, "127.0.0.1", listener.sockets[0].getsockname()[1])
            self.assertEqual(denied.exception.code, Code.OFFLINE)

    async def test_listener_failure_explains_port_conflict_or_missing_server(self) -> None:
        for status, code, message in (
            (21, Code.OFFLINE, "another program owns the configured loopback endpoint"),
            (22, Code.MODEL, "guarded model is not listening"),
            (1, Code.OFFLINE, "Windows Firewall rules"),
        ):
            with (self.subTest(status=status),
                  patch("stylus_jarvis.runtime.offline._run",
                        side_effect=subprocess.CalledProcessError(status, "checker", stderr=b"private detail")),
                  self.assertRaises(Failure) as failure):
                verify_listener("127.0.0.1", 11434)
            self.assertEqual(failure.exception.code, code)
            self.assertIn(message, str(failure.exception))
            self.assertNotIn("private detail", str(failure.exception))

    @unittest.skipUnless(os.getenv("STYLUS_NATIVE_ACCEPTANCE") == "1",
                         "requires the provisioned private MSI runtime and effective outbound rules")
    async def test_live_guarded_qwen_and_native_denial(self) -> None:
        root = Path(os.environ["LOCALAPPDATA"]) / "StylusJarvis"
        python = root / "runtime/python/python.exe"
        self.assertTrue(Path(sys.executable).samefile(python), "Run this test with the guarded Python image")
        await asyncio.to_thread(verify_application)
        checker = Path(__file__).resolve().parents[1] / "src/stylus_jarvis/runtime/offline-policy.ps1"
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        system = Path(os.environ["SystemRoot"]) / "System32"
        log = self.enterContext(tempfile.TemporaryFile())
        launcher = subprocess.Popen([
            str(system / "WindowsPowerShell/v1.0/powershell.exe"), "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "RemoteSigned", "-File", str(checker), "-Mode", "Serve",
            "-PythonImage", str(python), "-Port", str(port),
        ], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW)
        adapter = Ollama(Settings(port=port, output=96), load(root)[1])
        try:
            deadline = time.monotonic() + 60
            while True:
                if launcher.poll() is not None:
                    log.seek(0)
                    self.fail("Headless launch failed: " + log.read().decode(errors="replace")[-2000:])
                try:
                    _, ready = await asyncio.open_connection("127.0.0.1", port)
                    ready.close()
                    await ready.wait_closed()
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    await asyncio.sleep(.25)
            await adapter.probe()
            async with httpx.AsyncClient(trust_env=False) as client:
                version = await client.get(f"http://127.0.0.1:{port}/api/version")
                self.assertEqual(version.json()["version"], "0.40.17")
            # No Python audit hook in this test process. Require a policy denial
            # from Winsock, not a missing route, refused connection or timeout.
            def native_denial() -> int:
                with socket.socket() as native:
                    native.settimeout(2)
                    return native.connect_ex(("192.0.2.1", 443))
            self.assertEqual(await asyncio.to_thread(native_denial), 10013)
            chat = await asyncio.to_thread(subprocess.run, [sys.executable, "-B", __file__, "--guarded-chat", str(port)],
                                           capture_output=True, timeout=180)
            self.assertEqual(chat.returncode, 0, chat.stderr.decode(errors="replace")[-2000:])
            # Inspect the loaded model as well as the public HTTP endpoint.
            inspect = r"""
                $ErrorActionPreference = 'Stop'
                $listening = @(Get-NetTCPConnection -State Listen)
                $server = ($listening | Where-Object LocalPort -eq $env:STYLUS_TEST_PORT).OwningProcess
                $runners = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $server" |
                    Where-Object Name -eq 'llama-server.exe')
                if (-not $runners.Count) { throw 'The live model runner was not found.' }
                $expected = Join-Path $env:LOCALAPPDATA 'StylusJarvis\runtime\ollama\lib\ollama\llama-server.exe'
                foreach ($runner in $runners) {
                    if ($runner.ExecutablePath -ne $expected) { throw 'Unmanaged runner image.' }
                    $sockets = @($listening | Where-Object OwningProcess -eq $runner.ProcessId)
                    if (-not $sockets.Count) { throw 'No live runner listener.' }
                    foreach ($item in $sockets) {
                        if (-not [ipaddress]::IsLoopback([ipaddress]$item.LocalAddress)) { throw 'Exposed runner.' }
                    }
                }
            """
            observed = await asyncio.to_thread(subprocess.run, [
                str(system / "WindowsPowerShell/v1.0/powershell.exe"), "-NoProfile", "-NonInteractive",
                "-Command", inspect,
            ], env={**os.environ, "STYLUS_TEST_PORT": str(port)}, capture_output=True, timeout=30)
            self.assertEqual(observed.returncode, 0, observed.stderr.decode(errors="replace"))
        finally:
            await adapter.close()
            if launcher.poll() is None:
                # Only the dedicated test launcher and the processes it started.
                subprocess.run([str(system / "taskkill.exe"), "/PID", str(launcher.pid), "/T", "/F"],
                               capture_output=True, check=True, timeout=15)
            launcher.wait(timeout=10)


async def guarded_chat(port: int) -> None:
    await asyncio.to_thread(verify_application)
    root = Path(os.environ["LOCALAPPDATA"]) / "StylusJarvis"
    adapter = Ollama(Settings(port=port, output=96), load(root)[1])
    try:
        answer = "".join([p async for p in adapter.generate([ChatMessage("user", "Reply with OK.")])])
        if not answer.strip():
            raise AssertionError("Expected visible text from the local model")
    finally:
        await adapter.close()


if __name__ == "__main__":
    if sys.argv[1:] == ["--workers"]:
        exercise_workers()
    elif len(sys.argv) == 3 and sys.argv[1] == "--guarded-chat":
        install_worker_policy()
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication
        from qasync import QEventLoop

        app = QApplication([])
        with QEventLoop(app) as loop:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(guarded_chat(int(sys.argv[2])))
    else:
        unittest.main()
