import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from stylus_jarvis.editor.bridge import EditorBridge
from stylus_jarvis.editor.named_pipe import LocalPipe
from stylus_jarvis.editor.protocol import HEADER, MAX_FRAME, ProtocolError, decode_request, encode_frame
from stylus_jarvis.storage.database import Database
from stylus_jarvis.storage.editor_journal import EditorJournal
from stylus_jarvis.storage.repositories import Repositories

if os.name == "nt":
    import _winapi
    from stylus_jarvis.bootstrap import user_identity


def frame(operation: str, request_id: int = 1, **fields) -> bytes:
    return encode_frame({"operation": operation, "request_id": request_id,
                         "deadline_ms": time.time_ns() // 1_000_000 + 3000, **fields})


class WireTests(unittest.TestCase):
    def test_strict_fields_encodings_deadlines_and_versions(self) -> None:
        now = 1000
        valid = {"operation": "pair", "request_id": 1, "deadline_ms": 2000,
                 "versions": [1], "invitation": "a" * 43}
        self.assertEqual(decode_request(json.dumps(valid).encode(), now).operation, "pair")
        for changes in ({"deadline_ms": now}, {"deadline_ms": 10000}, {"versions": [2]},
                        {"versions": [True]}, {"request_id": True}, {"extra": 0}, {"operation": "edit"}):
            with self.subTest(changes=changes), self.assertRaises(ProtocolError):
                decode_request(json.dumps(valid | changes).encode(), now)
        for invalid in (b'{"request_id":1,"request_id":2}', b"\xff", b"[" * 1200, b"x" * (MAX_FRAME + 1)):
            with self.assertRaises(ProtocolError):
                decode_request(invalid, now)


@unittest.skipUnless(os.name == "nt", "Windows overlapped named pipes")
class WindowsBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.owner = user_identity()
        self.status: list[str] = []
        self.bridge = EditorBridge(self.owner, self.status.append)
        self.addAsyncCleanup(self.bridge.stop)

    def connect(self, name: str) -> LocalPipe:
        client = object.__new__(LocalPipe)
        client.handle = _winapi.CreateFile(name, 0xC0000000, 0, 0, 3, 0x40000000, 0)
        self.addCleanup(client.close)
        return client

    async def read(self, pipe: LocalPipe) -> dict:
        return json.loads(await asyncio.wait_for(pipe.receive(), 2))

    async def assert_rejected(self, pipe: LocalPipe) -> None:
        with self.assertRaises((EOFError, OSError)):
            await asyncio.wait_for(pipe.receive(), 2)

    async def authenticate(self, invitation: dict) -> tuple[LocalPipe, str]:
        client = self.connect(invitation["pipe"])
        await client.send(frame("pair", versions=[1], invitation=invitation["invitation"]))
        reply = await self.read(client)
        self.assertEqual(reply["capabilities"], ["ping"])
        return client, reply["session"]

    async def create_projects(self):
        scratch = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        roots = [scratch / parent / "Shared folder" for parent in ("Alpha", "Beta")]
        database = Database(scratch / "state/jarvis.sqlite3")
        await database.open()
        self.addAsyncCleanup(database.close)
        store = Repositories(database)
        scopes = []
        for root in roots:
            root.mkdir(parents=True)
            (root / "code #1.py").write_text("original\n", encoding="utf-8")
            project = await store.register(self.owner, root)
            scopes.append(await store.select(self.owner, project, len(scopes) + 1))
        self.current = scopes[0]
        self.bridge.store = store
        self.bridge.journal = EditorJournal(database)
        self.bridge.current_scope = lambda: self.current
        return database, roots, scopes

    async def pair_window(self, window: str, *, patches: bool = False):
        invite = json.loads(await self.bridge.issue(self.current))
        client = self.connect(invite["pipe"])
        options = {"patches": True} if patches else {}
        await client.send(frame("pair", versions=[1], invitation=invite["invitation"], window=window, **options))
        reply = await self.read(client)
        self.assertEqual(reply["window"], window)
        self.assertEqual(reply["binding"]["project"], self.current.project)
        self.assertEqual(reply["capabilities"], ["ping", "snapshot", "patch"] if patches else ["ping", "snapshot"])
        return client, reply

    @staticmethod
    def patch_target(metadata: dict, text: str) -> dict:
        return {"base": {key: metadata[key] for key in ("document_uri", "document_id", "document_version", "sha256")},
                "replacement": text}

    async def patch_request(self, client: LocalPipe, hello: dict, operation: str, request_id: int,
                            patch_body: dict) -> dict:
        identity = {key: hello[key] for key in ("window", "binding", "session", "version")}
        await client.send(frame(operation, request_id, patch=patch_body, **identity))
        return await self.read(client)

    async def test_patch_approval_matches_exact_digest_and_is_single_use(self) -> None:
        _, roots, _ = await self.create_projects()
        root = roots[0]
        client, hello = await self.pair_window(uuid4().hex, patches=True)
        other = root / "crlf.txt"
        other.write_bytes(b"saved\r\n")
        metadata = self.metadata(root)
        targets = [self.patch_target(metadata, "Unicode 🌿\n"),
                   self.patch_target(metadata | {"document_uri": other.as_uri(), "document_id": uuid4().hex},
                                     "change\r\n")]
        serialized = json.dumps({"workspace_uri": root.as_uri(), "targets": targets})
        digest = hashlib.sha256(serialized.encode()).hexdigest()
        preview = {"proposal": serialized, "digest": digest}
        approval = {"digest": digest, "approved": True, "observed": [item["base"] for item in targets]}
        async def ask(operation, request_id, body):
            return await self.patch_request(client, hello, operation, request_id, body)

        self.assertEqual((await ask("authorize_patch", 2, approval))["error"], "conflict")
        self.assertEqual((await ask("preview_patch", 3, preview | {"proposal": serialized + " "}))["error"], "conflict")
        self.assertEqual((await ask("preview_patch", 4, preview))["digest"], digest)
        self.assertEqual((await ask("authorize_patch", 5, approval | {"approved": False}))["error"], "conflict")
        self.assertTrue((await ask("preview_patch", 6, preview))["ok"])
        self.assertEqual((await ask("authorize_patch", 7, approval | {"digest": "f" * 64}))["error"], "conflict")
        self.assertTrue((await ask("preview_patch", 8, preview))["ok"])
        receipt = await ask("authorize_patch", 9, approval)
        self.assertEqual(receipt["digest"], digest)
        self.assertGreater(receipt["expires_ms"], time.time_ns() // 1_000_000)
        self.assertEqual((await ask("authorize_patch", 10, approval))["error"], "conflict")
        applied = targets[0]["base"] | {
            "sha256": hashlib.sha256(targets[0]["replacement"].encode()).hexdigest(),
            "document_version": 8,
        }
        result = await ask("recover_patch", 11, {"action": "result", "workspace_uri": root.as_uri(),
                                                "operation": receipt["operation_id"],
                                                "observed": [applied, targets[1]["base"]]})
        self.assertEqual(result["report"]["state"], "settled")
        self.assertEqual([target["outcome"] for target in result["report"]["targets"]], ["applied", "unchanged"])
        self.assertEqual(other.read_bytes(), b"saved\r\n")

    async def test_patch_rejects_unapproved_paths_stale_bases_and_grant_revocation(self) -> None:
        database, roots, scopes = await self.create_projects()
        client, hello = await self.pair_window(uuid4().hex, patches=True)
        metadata = self.metadata(roots[0])

        def proposal(document: dict) -> dict:
            serialized = json.dumps({"workspace_uri": roots[0].as_uri(),
                                     "targets": [self.patch_target(document, "changed")]})
            return {"proposal": serialized, "digest": hashlib.sha256(serialized.encode()).hexdigest()}

        foreign = proposal(metadata | {"document_uri": (roots[1] / "code #1.py").as_uri()})
        self.assertEqual((await self.patch_request(client, hello, "preview_patch", 2, foreign))["error"], "scope")
        good = proposal(metadata)
        self.assertTrue((await self.patch_request(client, hello, "preview_patch", 3, good))["ok"])
        base = self.patch_target(metadata, "")["base"]
        approval = {"digest": good["digest"], "approved": True, "observed": [base]}
        self.assertTrue((await self.share(client, hello, metadata | {"document_version": 8}, 4))["ok"])
        self.assertEqual((await self.patch_request(client, hello, "authorize_patch", 5, approval))["error"], "conflict")
        updated = metadata | {"document_version": 8}
        good = proposal(updated)
        self.assertTrue((await self.patch_request(client, hello, "preview_patch", 6, good))["ok"])
        await database.call(lambda conn: conn.execute("UPDATE projects SET grant=grant+1 WHERE id=?", (scopes[0].project,)),
                            write=True)
        identity = {key: hello[key] for key in ("window", "binding", "session", "version")}
        await client.send(frame("authorize_patch", 7, patch={"digest": good["digest"], "approved": True,
                                "observed": [self.patch_target(updated, "")["base"]]}, **identity))
        await self.assert_rejected(client)

    async def test_patch_recovery_preserves_partial_outcomes_across_restart_without_replay(self) -> None:
        database, roots, scopes = await self.create_projects()
        root = roots[0]
        other = root / "second.txt"
        other.write_bytes(b"saved\r\n")
        original = self.metadata(root)
        targets = [self.patch_target(original, "replacement 🌿\n"),
                   self.patch_target(original | {"document_uri": other.as_uri(), "document_id": uuid4().hex},
                                     "second replacement\r\n")]
        serialized = json.dumps({"workspace_uri": root.as_uri(), "targets": targets})
        digest = hashlib.sha256(serialized.encode()).hexdigest()
        preview = {"proposal": serialized, "digest": digest}
        approval = {"digest": digest, "approved": True, "observed": [target["base"] for target in targets]}
        client, hello = await self.pair_window(uuid4().hex, patches=True)
        self.assertTrue((await self.patch_request(client, hello, "preview_patch", 2, preview))["ok"])
        receipt = await self.patch_request(client, hello, "authorize_patch", 3, approval)
        operation = receipt["operation_id"]

        async def recover(peer, identity, request_id, action, workspace=root, **fields):
            return await self.patch_request(peer, identity, "recover_patch", request_id,
                                            {"action": action, "workspace_uri": workspace.as_uri(), **fields})

        await self.bridge.stop()
        await database.close()
        reopened = Database(database.path)
        await reopened.open()
        self.addAsyncCleanup(reopened.close)
        self.bridge.store = Repositories(reopened)
        self.bridge.journal = EditorJournal(reopened)
        client, hello = await self.pair_window(uuid4().hex, patches=True)
        self.assertEqual((await recover(client, hello, 2, "latest", roots[1]))["error"], "scope")
        pending = (await recover(client, hello, 3, "latest"))["report"]
        self.assertEqual((pending["operation"], pending["digest"], pending["state"]),
                         (operation, digest, "uncertain"))
        self.assertEqual((await recover(client, hello, 4, "result", operation=operation))["error"], "scope")
        self.assertEqual((await self.patch_request(client, hello, "preview_patch", 5, preview))["error"], "busy")
        with patch("stylus_jarvis.storage.editor_journal.now_ms", return_value=receipt["expires_ms"] - 1):
            self.assertEqual((await recover(client, hello, 6, "acknowledge", operation=operation))["error"], "busy")

        await reopened.call(lambda conn: conn.execute("UPDATE editor_patch_operations SET permit_expires_ms=0 "
                                                     "WHERE id=?", (operation,)), write=True)
        applied = targets[0]["base"] | {
            "sha256": hashlib.sha256(targets[0]["replacement"].encode()).hexdigest(),
            "document_version": 8,
        }
        reopened_base = targets[1]["base"] | {"document_id": uuid4().hex, "document_version": 1}
        partial = (await recover(client, hello, 7, "observe", operation=operation,
                                 observed=[applied, reopened_base]))["report"]
        self.assertEqual(partial["state"], "uncertain")
        self.assertEqual(partial["targets"], [{"path": "code #1.py", "outcome": "applied"},
                                              {"path": "second.txt", "outcome": "unresolved"}])
        self.assertEqual((await recover(client, hello, 8, "observe", operation=operation))["report"], partial)
        final = (await recover(client, hello, 9, "acknowledge", operation=operation))["report"]
        self.assertEqual(final["state"], "acknowledged")
        self.assertEqual(final["targets"], partial["targets"])
        self.assertTrue((await self.patch_request(client, hello, "preview_patch", 10, preview))["ok"])
        self.assertEqual((await self.patch_request(client, hello, "authorize_patch", 11, approval))["error"],
                         "conflict")
        self.assertEqual(other.read_bytes(), b"saved\r\n")
        self.assertEqual((root / "code #1.py").read_text(encoding="utf-8"), "original\n")
        await reopened.call(lambda conn: conn.execute("UPDATE projects SET grant=grant+1 WHERE id=?",
                                                     (scopes[0].project,)), write=True)
        identity = {key: hello[key] for key in ("window", "binding", "session", "version")}
        await client.send(frame("recover_patch", 12, patch={"action": "latest", "workspace_uri": root.as_uri()},
                                **identity))
        await self.assert_rejected(client)

    def metadata(self, root: Path) -> dict:
        start = {"line": 0, "character": 2}
        end = {"line": 1, "character": 5}
        return {"workspace_uri": root.as_uri(), "document_uri": (root / "code #1.py").as_uri(),
                "document_id": uuid4().hex, "document_version": 7, "dirty": True, "sha256": "a" * 64,
                "selection": {"anchor": end, "active": start},
                "diagnostics": [{"start": start, "end": end, "severity": 1, "message": "Fixture warning"}]}

    async def share(self, client: LocalPipe, reply: dict, snapshot: dict, request_id: int, **overrides):
        identity = {key: reply[key] for key in ("window", "binding", "session", "version")}
        await client.send(frame("snapshot", request_id, snapshot=snapshot, **(identity | overrides)))
        return await self.read(client)

    async def test_scoped_window_identity_and_revoked_grant(self) -> None:
        database, roots, scopes = await self.create_projects()
        first, hello = await self.pair_window(uuid4().hex)
        self.assertTrue((await self.share(first, hello, self.metadata(roots[0]), 2))["ok"])
        self.assertEqual(self.bridge.snapshot.window, hello["window"])
        self.assertEqual((await self.share(first, hello, self.metadata(roots[1]), 3))["error"], "scope")
        self.current = scopes[1]
        second, next_hello = await self.pair_window(uuid4().hex)
        await self.assert_rejected(first)
        self.assertIsNone(self.bridge.snapshot)
        self.assertTrue((await self.share(second, next_hello, self.metadata(roots[1]), 2))["ok"])
        self.assertEqual(self.bridge.snapshot.scope.project, scopes[1].project)
        self.assertEqual(self.bridge.snapshot.workspace, roots[1])
        await second.send(frame("snapshot", 3, version=1, session=next_hello["session"],
                                binding=next_hello["binding"], window=hello["window"],
                                snapshot=self.metadata(roots[1])))
        await self.assert_rejected(second)
        client, next_hello = await self.pair_window(uuid4().hex)
        await database.call(lambda conn: conn.execute("UPDATE projects SET grant=grant+1 WHERE id=?",
                            (scopes[1].project,)), write=True)
        await client.send(frame("snapshot", 2, version=1, session=next_hello["session"],
                                binding=next_hello["binding"], window=next_hello["window"],
                                snapshot=self.metadata(roots[1])))
        await self.assert_rejected(client)
        self.assertIsNone(self.bridge.snapshot)

    async def test_snapshot_ranges_dirty_state_and_document_reopen(self) -> None:
        _, roots, _ = await self.create_projects()
        client, hello = await self.pair_window(uuid4().hex)
        original = self.metadata(roots[0])
        self.assertTrue((await self.share(client, hello, original, 2))["ok"])
        record = self.bridge.snapshot
        self.assertEqual(record.relative_path, "code #1.py")
        self.assertEqual(record.metadata.selection.model_dump(), original["selection"])
        self.assertEqual(record.metadata.diagnostics[0].model_dump(), original["diagnostics"][0])
        self.assertTrue(record.metadata.dirty)
        self.assertTrue((await self.share(client, hello, original | {"dirty": False}, 3))["ok"])
        self.assertFalse(self.bridge.snapshot.metadata.dirty)
        self.assertEqual((await self.share(client, hello, original | {"document_version": 6}, 4))["error"], "conflict")
        self.assertEqual((await self.share(client, hello, original | {"sha256": "b" * 64}, 5))["error"], "conflict")
        reopened = original | {"document_id": uuid4().hex, "document_version": 1}
        self.assertTrue((await self.share(client, hello, reopened, 6))["ok"])
        self.assertEqual(self.bridge.snapshot.metadata.document_id, reopened["document_id"])
        self.assertEqual((await self.share(client, hello, original, 7))["error"], "conflict")

    async def test_rejects_remote_authorities_and_junction_escapes(self) -> None:
        from _winapi import CreateJunction

        _, roots, _ = await self.create_projects()
        client, hello = await self.pair_window(uuid4().hex)
        original = self.metadata(roots[0])
        escape = roots[0] / "Linked"
        CreateJunction(str(roots[1]), str(escape))
        cases = ({"workspace_uri": "vscode-remote://ssh-remote+test/project"},
                 {"document_uri": "file://localhost/C:/example.py"},
                 {"document_uri": (roots[1] / "code #1.py").as_uri()},
                 {"document_uri": (escape / "code #1.py").as_uri()})
        for request_id, changes in enumerate(cases, 2):
            self.assertIn((await self.share(client, hello, original | changes, request_id))["error"],
                          ("scope", "offline_policy"))
            self.assertIsNone(self.bridge.snapshot)

    async def test_pair_wrong_credential_peer_replay_and_stale_session(self) -> None:
        invitation = json.loads(await self.bridge.issue())
        wrong = self.connect(invitation["pipe"])
        await wrong.send(frame("pair", versions=[1], invitation="a" * 43))
        await self.assert_rejected(wrong)
        with patch.object(LocalPipe, "peer_sid", return_value="S-1-5-7"):
            wrong_user = self.connect(invitation["pipe"])
            await wrong_user.send(frame("pair", versions=[1], invitation=invitation["invitation"]))
            await self.assert_rejected(wrong_user)
        client, session = await self.authenticate(invitation)
        await client.send(frame("ping", 2, version=1, session=session))
        self.assertEqual(await self.read(client), {"request_id": 2, "version": 1, "ok": True})
        await client.send(frame("ping", 2, version=1, session=session))
        await self.assert_rejected(client)
        with self.assertRaises(OSError):
            self.connect(invitation["pipe"])
        fresh = json.loads(await self.bridge.issue())
        fresh_client, _ = await self.authenticate(fresh)
        await fresh_client.send(frame("ping", 2, version=1, session=session))
        await self.assert_rejected(fresh_client)

    async def test_acl_denies_a_token_outside_the_allowed_sid(self) -> None:
        name = rf"\\.\pipe\stylus-jarvis-editor-{uuid4().hex}"
        pipe = LocalPipe(name, "S-1-5-7")
        self.addCleanup(pipe.close)
        with self.assertRaises(OSError) as denied:
            self.connect(name)
        self.assertEqual(denied.exception.winerror, 5)
        with self.assertRaises(OSError):
            LocalPipe(name, self.owner)

    async def test_oversized_frame_and_repair_cancel_existing_transport(self) -> None:
        invitation = json.loads(await self.bridge.issue())
        malformed = self.connect(invitation["pipe"])
        await malformed.send(HEADER.pack(MAX_FRAME + 1))
        await self.assert_rejected(malformed)
        client, _ = await self.authenticate(invitation)
        await asyncio.wait_for(self.bridge.issue(), 1)
        await self.assert_rejected(client)
        await asyncio.wait_for(self.bridge.stop(), 1)
        self.assertEqual(self.status[-1], "VS Code disconnected")

    async def test_invitation_and_session_expire(self) -> None:
        with patch("stylus_jarvis.editor.bridge.INVITATION_SECONDS", .08):
            expired = json.loads(await self.bridge.issue())
            await asyncio.sleep(.15)
            with self.assertRaises(OSError):
                self.connect(expired["pipe"])
        with patch("stylus_jarvis.editor.bridge.SESSION_SECONDS", .15):
            active, _ = await self.authenticate(json.loads(await self.bridge.issue()))
            await self.assert_rejected(active)

    async def test_partial_frame_cannot_hold_the_listener_past_invitation_expiry(self) -> None:
        with patch("stylus_jarvis.editor.bridge.INVITATION_SECONDS", .2):
            invitation = json.loads(await self.bridge.issue())
            client = self.connect(invitation["pipe"])
            await client.send(b"\x01\x00")
            await self.assert_rejected(client)

    async def test_compiled_extension_client_pairs_over_the_native_pipe(self) -> None:
        client = Path("extensions/vscode/dist/client.js").resolve()
        node = shutil.which("node")
        if not client.is_file() or not node:
            self.skipTest("build the VS Code extension to exercise its native pipe client")
        javascript = """
const { EditorClient } = require(process.argv[1]);
let ticket = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', part => ticket += part);
process.stdin.on('end', async () => {
    try {
        const client = await EditorClient.connect(ticket, () => {});
        await client.ping();
        client.close();
        console.log('paired and pinged');
    } catch {
        process.exitCode = 1;
    }
});
"""
        result = await asyncio.to_thread(subprocess.run, [node, "-e", javascript, str(client)],
                                         input=await self.bridge.issue(), text=True, capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "paired and pinged")
