"""Round-trip sample history between the schema-1 revision and the installed release."""
import asyncio
import io
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

PREVIOUS = "f6c7aad3606d64931f0537047249bdb05fda3933"


async def inspect_store(action: str, root: Path, database: Path) -> None:
    if action in ("seed", "rollback"):
        sys.path.insert(0, str(root / "previous/src"))
    from stylus_jarvis.contracts.messages import State
    from stylus_jarvis.storage.database import Database
    from stylus_jarvis.storage.repositories import Repositories

    db = Database(database)
    await db.open()
    try:
        repo = Repositories(db)
        record = root / "selection.json"
        if action == "seed":
            project = await repo.register("sample", root)
            scope = await repo.select("sample", project, 1)
            turn, _ = await repo.begin(scope, uuid4(), "Sample question", "1" * 64)
            await repo.finish(scope, turn.key, State.COMPLETED, "Sample answer", None)
            record.write_text(json.dumps([project, scope.conversation]))
        project, thread = json.loads(record.read_bytes())
        scope = await repo.select("sample", project, 1, thread)
        history = await repo.history(scope)
        if [r[1:] for r in history] != [("user", "Sample question", "completed"),
                                         ("assistant", "Sample answer", "completed")]:
            raise RuntimeError("The sample conversation changed")
        version = await db.call(lambda c: c.execute("SELECT max(version) FROM migrations").fetchone()[0])
        if version != (2 if action == "upgrade" else 1):
            raise RuntimeError("Unexpected restored schema")
    finally:
        await db.close()


def rehearse() -> None:
    from stylus_jarvis.settings import profile_path
    if profile_path().name != "StylusJarvis-Rehearsal" or not sys.flags.isolated:
        raise ValueError("Use the installed rehearsal interpreter with -I")
    repo = Path(__file__).resolve().parents[2]
    archive = subprocess.check_output(["git", "-c", "core.autocrlf=false", "archive",
                                       "--format=zip", PREVIOUS, "src/stylus_jarvis"], cwd=repo)
    with tempfile.TemporaryDirectory() as work:
        root = Path(work)
        with zipfile.ZipFile(io.BytesIO(archive)) as snapshot:
            snapshot.extractall(root / "previous")
        database = root / "sample/store.sqlite3"
        def run(action: str, path: Path) -> None:
            subprocess.run([sys.executable, "-I", "-B", __file__, action, str(root), str(path)], check=True)
        run("seed", database)
        run("upgrade", database)
        backup, = database.parent.glob("*.pre-2-*.sqlite3")
        restored = root / "restored/store.sqlite3"
        restored.parent.mkdir()
        shutil.copyfile(backup, restored)
        run("rollback", restored)
    print("PASS: schema 1 -> 2 -> 1; prior release reopened the original project and completed conversation.")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        rehearse()
    else:
        asyncio.run(inspect_store(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])))
