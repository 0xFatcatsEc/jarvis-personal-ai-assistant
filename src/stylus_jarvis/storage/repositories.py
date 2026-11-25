"""Scoped project, conversation and turn operations. SQL never escapes this boundary."""
import asyncio
import os
import sqlite3
from collections.abc import Callable
from dataclasses import astuple, dataclass
from pathlib import Path
from uuid import UUID, uuid4

from ..contracts.messages import ChatMessage, Code, Failure, PendingSave, Scope, State, Turn
from ..settings import check_local_route
from ..knowledge.ingestion import SourceRevision, fingerprint
from ..knowledge.locators import Locator, extract
from ..knowledge.context import Citation, EvidenceBundle, Passage, assemble, concepts
from ..memory.service import Destination, Fact, FactDraft, Origin
from ..memory.export import write_manifest
from .database import Database
from .deletions import open_ledger, reconcile
from . import recovery


_FACT_SELECT = ("SELECT f.id,v.version,f.owner,f.project,v.text,v.origin,v.locator,r.source,l.revision "
                "FROM facts f JOIN fact_versions v ON v.fact=f.id "
                "LEFT JOIN evidence_locators l ON l.id=v.locator "
                "LEFT JOIN source_revisions r ON r.id=l.revision ")

_DISPLAY_STATE = "CASE WHEN t.state='failed' AND t.error='token_limit' THEN 'token_limit' ELSE t.state END"


@dataclass(frozen=True, slots=True)
class SearchHit:
    source: str
    revision: str
    locator: str
    relative_path: str


def _authorize(conn: sqlite3.Connection, scope: Scope) -> None:
    row = conn.execute(
        "SELECT p.grant FROM projects p JOIN conversations c ON c.project=p.id "
        "WHERE p.owner=? AND p.id=? AND c.id=?", (scope.owner, scope.project, scope.conversation)
    ).fetchone()
    if row is None or row[0] != scope.grant or not scope.offline:
        raise Failure(Code.SCOPE)


def _turn(conn: sqlite3.Connection, scope: Scope, key: str) -> Turn:
    row = conn.execute(
        f"SELECT t.id,u.content,a.content,{_DISPLAY_STATE} FROM turns t "
        "JOIN messages u ON u.turn=t.id AND u.role='user' "
        "JOIN messages a ON a.turn=t.id AND a.role='assistant' "
        "WHERE t.conversation=? AND t.id=?", (scope.conversation, key)
    ).fetchone()
    if not row:
        raise Failure(Code.SCOPE)
    return Turn(row[0], row[1], row[2], State(row[3]))


def _lookup(conn: sqlite3.Connection, scope: Scope, request: UUID, text: str) -> Turn | None:
    row = conn.execute("SELECT id FROM turns WHERE conversation=? AND submission=?",
                       (scope.conversation, request.hex)).fetchone()
    if row is None:
        return None
    turn = _turn(conn, scope, row[0])
    if turn.question != text:
        raise Failure(Code.CONFLICT)
    return turn


class Repositories:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def register(self, owner: str, root: Path) -> str:
        def resolve() -> Path:
            try:
                check_local_route(root)
                path = root.resolve(strict=True)
                if not path.is_dir() or str(path).startswith("\\\\"):
                    raise Failure(Code.SCOPE)
                return path
            except OSError as exc:
                raise Failure(Code.SCOPE) from exc
        path = await asyncio.to_thread(resolve)
        identity = os.path.normcase(str(path))

        def register(conn: sqlite3.Connection) -> str:
            conn.execute("INSERT INTO projects(id,owner,root,identity) VALUES(?,?,?,?) "
                         "ON CONFLICT(owner,identity) DO NOTHING", (uuid4().hex, owner, str(path), identity))
            return str(conn.execute("SELECT id FROM projects WHERE owner=? AND identity=?", (owner, identity)).fetchone()[0])
        return await self.db.call(register, write=True)

    async def projects(self, owner: str) -> list[tuple[str, str]]:
        return await self.db.call(lambda c: [(r[0], r[1]) for r in c.execute(
            "SELECT id,root FROM projects WHERE owner=? ORDER BY root", (owner,))])

    async def approve_source(self, scope: Scope, selected: Path, *,
                             checkpoint: Callable[[], None] | None = None) -> SourceRevision:
        """Register the current content of a file explicitly selected by the owner."""
        def approved_root(conn: sqlite3.Connection) -> Path:
            _authorize(conn, scope)
            return Path(conn.execute("SELECT root FROM projects WHERE id=?", (scope.project,)).fetchone()[0])

        root = await self.db.call(approved_root)
        args = (root, selected) if checkpoint is None else (root, selected, checkpoint)
        relative, digest, size = await asyncio.to_thread(fingerprint, *args)
        if checkpoint is not None:
            await asyncio.to_thread(checkpoint)

        def record(conn: sqlite3.Connection) -> SourceRevision:
            _authorize(conn, scope)
            conn.execute("INSERT INTO sources VALUES(?,?,?) ON CONFLICT(project,relative_path) DO NOTHING",
                         (uuid4().hex, scope.project, relative))
            source = conn.execute("SELECT id FROM sources WHERE project=? AND relative_path=?",
                                  (scope.project, relative)).fetchone()[0]
            conn.execute("INSERT INTO source_revisions VALUES(?,?,?,?) ON CONFLICT(source,sha256) DO NOTHING",
                         (uuid4().hex, source, digest, size))
            revision = conn.execute("SELECT id FROM source_revisions WHERE source=? AND sha256=?",
                                    (source, digest)).fetchone()[0]
            return SourceRevision(source, revision, relative, digest, size)

        receipt = await self.db.call(record, write=True)
        await self.validate(scope)
        return receipt

    async def source_revision(self, scope: Scope, source_id: str, revision_id: str) -> SourceRevision:
        def fetch(conn: sqlite3.Connection) -> SourceRevision:
            _authorize(conn, scope)
            row = conn.execute("SELECT s.id,r.id,s.relative_path,r.sha256,r.byte_count FROM sources s "
                               "JOIN source_revisions r ON r.source=s.id WHERE s.project=? AND s.id=? AND r.id=?",
                               (scope.project, source_id, revision_id)).fetchone()
            if row is None:
                raise Failure(Code.SCOPE)
            return SourceRevision(*row)
        revision = await self.db.call(fetch)
        await self.validate(scope)
        return revision

    async def saved_code_revisions(self, scope: Scope) -> list[SourceRevision]:
        def read(conn: sqlite3.Connection) -> list[SourceRevision]:
            _authorize(conn, scope)
            rows = conn.execute(
                "SELECT s.id,r.id,s.relative_path,r.sha256,r.byte_count FROM sources s "
                "JOIN source_revisions r ON r.source=s.id WHERE s.project=? AND EXISTS "
                "(SELECT 1 FROM evidence_locators l WHERE l.revision=r.id AND l.page IS NULL "
                "AND l.ocr_needed=0 AND trim(l.excerpt)<>'') ORDER BY s.relative_path,r.rowid DESC",
                (scope.project,))
            return [SourceRevision(*row) for row in rows]

        revisions = await self.db.call(read)
        await self.validate(scope)
        return revisions

    async def saved_code_context(self, scope: Scope, source: str, revision: str, max_bytes: int) -> EvidenceBundle:
        if not 2 <= max_bytes <= 65536:
            raise Failure(Code.INPUT)

        def read(conn: sqlite3.Connection) -> EvidenceBundle:
            _authorize(conn, scope)
            rows = conn.execute(
                "SELECT s.id,r.id,l.id,s.relative_path,l.page,l.start,l.end,l.excerpt "
                "FROM evidence_locators l JOIN source_revisions r ON r.id=l.revision "
                "JOIN sources s ON s.id=r.source WHERE s.project=? AND s.id=? AND r.id=? "
                "AND l.page IS NULL AND l.ocr_needed=0 AND trim(l.excerpt)<>'' ORDER BY l.start LIMIT 32",
                (scope.project, source, revision))
            return assemble((Passage(row[-1], (Citation(*row[:-1]),)) for row in rows), max_bytes, 8)

        bundle = await self.db.call(read)
        await self.validate(scope)
        return bundle

    @staticmethod
    def _locators(conn: sqlite3.Connection, scope: Scope, source: str, revision: str,
                  locator: str | None = None) -> list[Locator]:
        _authorize(conn, scope)
        sql = ("SELECT l.id,l.revision,l.extractor,l.page,l.start,l.end,l.excerpt,l.ocr_needed "
               "FROM evidence_locators l JOIN source_revisions r ON r.id=l.revision "
               "JOIN sources s ON s.id=r.source WHERE s.project=? AND s.id=? AND r.id=?")
        args = [scope.project, source, revision]
        if locator is not None:
            sql += " AND l.id=?"
            args.append(locator)
        return [Locator(*row[:-1], bool(row[-1])) for row in conn.execute(sql + " ORDER BY l.page,l.start", args)]

    async def extract_locators(self, scope: Scope, source: str, revision: str, *,
                               checkpoint: Callable[[], None] | None = None) -> list[Locator]:
        approved = await self.source_revision(scope, source, revision)

        def prepare(conn: sqlite3.Connection) -> tuple[Path, list[Locator]]:
            cached = self._locators(conn, scope, source, revision)
            root = conn.execute("SELECT root FROM projects WHERE id=?", (scope.project,)).fetchone()[0]
            return Path(root), cached

        root, records = await self.db.call(prepare)
        if not records:
            args = (root, approved) if checkpoint is None else (root, approved, checkpoint)
            extracted = await asyncio.to_thread(extract, *args)
            if checkpoint is not None:
                await asyncio.to_thread(checkpoint)

            def publish(conn: sqlite3.Connection) -> list[Locator]:
                existing = self._locators(conn, scope, source, revision)
                if existing:
                    return existing
                conn.executemany("INSERT INTO evidence_locators "
                                 "(id,revision,extractor,page,start,end,excerpt,ocr_needed) VALUES(?,?,?,?,?,?,?,?)",
                                 (astuple(item) for item in extracted))
                return extracted

            records = await self.db.call(publish, write=True)
        await self.validate(scope)
        return records

    async def resolve_locator(self, scope: Scope, source: str, revision: str, locator: str) -> Locator:
        records = await self.db.call(lambda c: self._locators(c, scope, source, revision, locator))
        if not records:
            raise Failure(Code.SCOPE)
        await self.validate(scope)
        return records[0]

    async def active_revision(self, scope: Scope, source: str) -> str | None:
        def lookup(conn: sqlite3.Connection) -> str | None:
            _authorize(conn, scope)
            row = conn.execute("SELECT a.revision FROM active_evidence a JOIN sources s ON s.id=a.source "
                               "WHERE s.project=? AND s.id=?", (scope.project, source)).fetchone()
            return str(row[0]) if row else None
        return await self.db.call(lookup)

    async def publish_revision(self, scope: Scope, source: str, revision: str, *,
                               replaces: tuple[str, str] | None = None) -> None:
        """Activate a complete extracted revision. Supply the old active pair for a replacement or move."""
        def publish(conn: sqlite3.Connection) -> None:
            _authorize(conn, scope)
            target = conn.execute(
                "SELECT 1 FROM sources s JOIN source_revisions r ON s.id=r.source "
                "WHERE s.project=? AND s.id=? AND r.id=?", (scope.project, source, revision)).fetchone()
            if target is None:
                raise Failure(Code.SCOPE)
            if replaces is not None and not conn.execute(
                "SELECT 1 FROM source_revisions r JOIN sources s ON s.id=r.source "
                "WHERE r.source=? AND r.id=? AND s.project=?", (*replaces, scope.project)
            ).fetchone():
                raise Failure(Code.SCOPE)
            current = conn.execute("SELECT revision FROM active_evidence WHERE source=?", (source,)).fetchone()
            if current and current[0] == revision:
                if replaces and replaces[0] != source:
                    prior = conn.execute("SELECT a.revision FROM active_evidence a JOIN sources s ON s.id=a.source "
                                         "WHERE s.project=? AND s.id=?", (scope.project, replaces[0])).fetchone()
                    if prior and prior[0] != replaces[1]:
                        raise Failure(Code.CONFLICT)
                    if prior:
                        conn.execute("DELETE FROM active_evidence WHERE source=? AND revision=?", replaces)
                return
            if current and replaces != (source, current[0]):
                raise Failure(Code.CONFLICT)
            indexed = conn.execute("SELECT 1 FROM evidence_locators l JOIN indexed_locators i ON i.locator=l.id "
                                   "WHERE l.revision=? LIMIT 1", (revision,)).fetchone()
            if indexed and replaces is None:
                raise Failure(Code.CONFLICT)
            if replaces is not None:
                removed = conn.execute("DELETE FROM active_evidence WHERE source=? AND revision=? AND source IN "
                                       "(SELECT id FROM sources WHERE project=?)", (*replaces, scope.project))
                if removed.rowcount != 1:
                    raise Failure(Code.CONFLICT)
            if not indexed:
                inserted = conn.execute("INSERT INTO indexed_locators(locator) "
                                        "SELECT id FROM evidence_locators WHERE revision=?", (revision,))
                if not inserted.rowcount:
                    raise Failure(Code.CONFLICT)
            conn.execute("INSERT INTO active_evidence(source,revision) VALUES(?,?)", (source, revision))

        await self.db.call(publish, write=True)
        await self.validate(scope)

    async def search_evidence(self, scope: Scope, phrase: str, *, revision: str | None = None,
                              limit: int = 50) -> list[SearchHit]:
        """Literal phrase search of active sources, or of one explicitly named published revision."""
        if not phrase.strip() or len(phrase) > 512 or "\x00" in phrase or not 1 <= limit <= 200:
            raise Failure(Code.INPUT)
        literal = '"' + phrase.replace('"', '""') + '"'

        def search(conn: sqlite3.Connection) -> list[SearchHit]:
            _authorize(conn, scope)
            query = ("SELECT s.id,r.id,l.id,s.relative_path FROM evidence_fts "
                     "JOIN indexed_locators i ON i.posting=evidence_fts.rowid "
                     "JOIN evidence_locators l ON l.id=i.locator JOIN source_revisions r ON r.id=l.revision "
                     "JOIN sources s ON s.id=r.source ")
            args = [scope.project, literal]
            if revision is None:
                query += "JOIN active_evidence a ON a.revision=r.id AND a.source=s.id "
            query += "WHERE s.project=? AND evidence_fts MATCH ? "
            if revision is not None:
                query += "AND r.id=? "
                args.append(revision)
            return [SearchHit(*row) for row in conn.execute(
                query + "ORDER BY s.relative_path,l.page,l.start LIMIT ?", (*args, limit))]

        hits = await self.db.call(search)
        await self.validate(scope)
        return hits

    async def cited_context(self, scope: Scope, question: str, *, revision: str | None = None,
                            max_bytes: int = 8192, max_passages: int = 8) -> EvidenceBundle:
        if not question.strip() or len(question) > 512 or not 2 <= max_bytes <= 65536 or not 1 <= max_passages <= 32:
            raise Failure(Code.INPUT)
        terms = concepts(question)
        if len(terms) > 32:
            raise Failure(Code.INPUT)

        def read(conn: sqlite3.Connection) -> EvidenceBundle:
            _authorize(conn, scope)
            if not terms:
                return EvidenceBundle(())
            matches = " UNION ALL ".join("SELECT rowid FROM evidence_fts WHERE evidence_fts MATCH ?" for _ in terms)
            selection = "AND r.id=?" if revision is not None else (
                "AND EXISTS(SELECT 1 FROM active_evidence a WHERE a.source=s.id AND a.revision=r.id)")
            sql = f"""WITH matches(posting) AS ({matches})
                SELECT s.id,r.id,l.id,s.relative_path,l.page,l.start,l.end,l.excerpt
                FROM matches JOIN indexed_locators i ON i.posting=matches.posting
                JOIN evidence_locators l ON l.id=i.locator JOIN source_revisions r ON r.id=l.revision
                JOIN sources s ON s.id=r.source WHERE s.project=? AND l.ocr_needed=0 {selection}
                GROUP BY l.id HAVING count(*) > ?
                ORDER BY count(*) DESC,s.relative_path,l.page,l.start,l.id"""
            args = [*terms, scope.project]
            if revision is not None:
                args.append(revision)
            rows = conn.execute(sql, (*args, len(terms) // 2))
            candidates = (Passage(row[-1], (Citation(*row[:-1]),)) for row in rows)
            return assemble(candidates, max_bytes, max_passages)

        bundle = await self.db.call(read)
        await self.validate(scope)
        return bundle

    async def confirm_fact(self, scope: Scope, draft: FactDraft, *, confirmed: bool) -> Fact | None:
        return await self._save_fact(scope, draft, confirmed, predecessor=None)

    async def correct_fact(self, scope: Scope, draft: FactDraft, *, expected_version: int,
                           confirmed: bool) -> Fact | None:
        """Confirm a replacement statement for draft.id at the reviewed version."""
        if type(expected_version) is not int or not 1 <= expected_version < 2**63 - 1:
            raise Failure(Code.INPUT)
        return await self._save_fact(scope, draft, confirmed, predecessor=expected_version)

    async def _save_fact(self, scope: Scope, draft: FactDraft, confirmed: bool,
                         predecessor: int | None) -> Fact | None:
        if confirmed is not True:
            return None
        if draft.scope != scope:
            raise Failure(Code.SCOPE)
        project = scope.project if draft.destination == Destination.PROJECT else None
        version = 1 if predecessor is None else predecessor + 1
        key = draft.id.hex

        def save(conn: sqlite3.Connection) -> None:
            _authorize(conn, scope)
            evidence = None
            if draft.locator is not None:
                evidence = conn.execute(
                    "SELECT s.id,r.sha256 FROM evidence_locators l JOIN source_revisions r ON r.id=l.revision "
                    "JOIN sources s ON s.id=r.source WHERE l.id=? AND s.project=?",
                    (draft.locator, project)).fetchone()
                if evidence is None:
                    raise Failure(Code.SCOPE)
            with open_ledger(conn, self.db.deletion_path()) as ledger:
                if ledger.conn.execute("SELECT 1 FROM deletions WHERE fact=?", (key,)).fetchone():
                    raise Failure(Code.SCOPE)
                if draft.origin == Origin.INFERRED:
                    tokens = [ledger.text_token(scope.owner, project, draft.text)]
                    if evidence is not None:
                        tokens.extend(ledger.token(kind, scope.owner, project, value)
                                      for kind, value in zip(("source", "digest"), evidence, strict=True))
                    if ledger.blocks(tokens):
                        raise Failure(Code.CONFLICT)
            payload = (draft.text, draft.origin.value, scope.conversation, scope.grant, draft.locator)
            if predecessor is not None:
                head = conn.execute("SELECT MAX(v.version) FROM facts f JOIN fact_versions v ON f.id=v.fact "
                                    "WHERE f.id=? AND f.owner=? AND f.project IS ?",
                                    (key, scope.owner, project)).fetchone()[0]
                if head is None:
                    raise Failure(Code.SCOPE)
                if head != predecessor:
                    raise Failure(Code.CONFLICT)
            else:
                inserted = conn.execute("INSERT INTO facts(id,owner,project) VALUES(?,?,?) ON CONFLICT(id) DO NOTHING",
                                        (key, scope.owner, project))
                if not inserted.rowcount:
                    prior = conn.execute("SELECT v.text,v.origin,v.conversation,v.grant_revision,v.locator "
                                         "FROM fact_versions v JOIN facts f ON f.id=v.fact WHERE f.id=? "
                                         "AND f.owner=? AND f.project IS ? AND v.version=1",
                                         (key, scope.owner, project)).fetchone()
                    if prior is None or tuple(prior) != payload:
                        raise Failure(Code.CONFLICT)
                    return
            conn.execute("INSERT INTO fact_versions(fact,version,text,origin,conversation,grant_revision,locator) "
                         "VALUES(?,?,?,?,?,?,?)", (key, version, *payload))

        await self.db.call(save, write=True)
        return await self.get_fact(scope, key, destination=draft.destination, version=version)

    async def forget_fact(self, scope: Scope, fact_id: str, *, expected_version: int, confirmed: bool,
                          destination: Destination = Destination.PROJECT) -> bool:
        if confirmed is not True:
            return False
        if not isinstance(destination, Destination) or type(expected_version) is not int or expected_version < 1:
            raise Failure(Code.INPUT)
        project = scope.project if destination == Destination.PROJECT else None

        def forget(conn: sqlite3.Connection) -> None:
            _authorize(conn, scope)
            with open_ledger(conn, self.db.deletion_path()) as ledger:
                prior = ledger.conn.execute("SELECT version FROM deletions WHERE fact=? AND scope=?",
                    (fact_id, ledger.token("scope", scope.owner, project))).fetchone()
                if prior is not None:
                    if prior[0] != expected_version:
                        raise Failure(Code.CONFLICT)
                else:
                    versions = conn.execute(_FACT_SELECT + " WHERE f.id=? AND f.owner=? AND f.project IS ? "
                                            "ORDER BY v.version DESC", (fact_id, scope.owner, project)).fetchall()
                    if not versions:
                        raise Failure(Code.SCOPE)
                    if versions[0][1] != expected_version:
                        raise Failure(Code.CONFLICT)
                    tokens = {ledger.text_token(scope.owner, project, version[4]) for version in versions}
                    for source, digest in conn.execute(
                        "SELECT r.source,r.sha256 FROM fact_versions v JOIN evidence_locators l ON l.id=v.locator "
                        "JOIN source_revisions r ON r.id=l.revision WHERE v.fact=?", (fact_id,)
                    ):
                        tokens.add(ledger.token("source", scope.owner, project, source))
                        tokens.add(ledger.token("digest", scope.owner, project, digest))
                    ledger.record(fact_id, ledger.token("scope", scope.owner, project), expected_version, tokens)
                reconcile(conn, ledger)

        await self.db.call(forget, write=True)
        return True

    def _active_facts(self, conn: sqlite3.Connection, owner: str, project: str | None) -> list[Fact]:
        rows = conn.execute(_FACT_SELECT + " WHERE f.owner=? AND f.project IS ? AND v.version="
                            "(SELECT MAX(h.version) FROM fact_versions h WHERE h.fact=f.id) ORDER BY f.id",
                            (owner, project))
        with open_ledger(conn, self.db.deletion_path()) as ledger:
            return [Fact(*row[:5], Origin(row[5]), *row[6:]) for row in rows
                    if not ledger.forgotten(row[0], owner, project)]

    async def recall_facts(self, scope: Scope, *, destination: Destination = Destination.PROJECT) -> list[Fact]:
        if not isinstance(destination, Destination):
            raise Failure(Code.INPUT)
        project = scope.project if destination == Destination.PROJECT else None

        def read(conn: sqlite3.Connection) -> list[Fact]:
            _authorize(conn, scope)
            return self._active_facts(conn, scope.owner, project)
        facts = await self.db.call(read)
        await self.validate(scope)
        return facts

    async def export_project(self, scope: Scope, target: Path) -> Path:
        """Publish one project's settled history and current confirmed facts."""
        def export(conn: sqlite3.Connection) -> Path:
            _authorize(conn, scope)
            histories = {row["id"]: dict(row) | {"messages": []} for row in conn.execute(
                "SELECT id,title,created_at FROM conversations WHERE project=? ORDER BY rowid", (scope.project,))}
            for row in conn.execute(
                f"SELECT m.conversation,m.seq,m.turn,m.role,m.content,{_DISPLAY_STATE} AS state "
                "FROM messages m JOIN conversations c ON c.id=m.conversation JOIN turns t ON t.id=m.turn "
                "WHERE c.project=? AND t.state!='active' ORDER BY c.rowid,m.seq", (scope.project,)
            ):
                message = dict(row)
                histories[message.pop("conversation")]["messages"].append(message)

            facts = []
            for fact in self._active_facts(conn, scope.owner, scope.project):
                evidence = None
                if fact.locator is not None:
                    row = conn.execute(
                        "SELECT s.id AS source_id,r.id AS revision_id,l.id AS locator_id,"
                        "s.relative_path,r.sha256,l.page,l.start,l.end FROM evidence_locators l "
                        "JOIN source_revisions r ON r.id=l.revision JOIN sources s ON s.id=r.source "
                        "WHERE l.id=? AND s.project=?", (fact.locator, scope.project)).fetchone()
                    if row is None:
                        raise Failure(Code.STORE)
                    evidence = dict(row)
                facts.append({"id": fact.id, "version": fact.version, "text": fact.text,
                              "origin": fact.origin.value, "evidence": evidence})
            return write_manifest(target, {"format": "stylus-jarvis-project", "version": 1,
                                           "project_id": scope.project, "conversations": list(histories.values()),
                                           "facts": facts})

        # Serialize publication with grant updates and forgetting. The export has
        # no database changes, but an immediate transaction fixes the ordering.
        return await self.db.call(export, write=True)

    async def get_fact(self, scope: Scope, fact_id: str, *, destination: Destination = Destination.PROJECT,
                       version: int = 1) -> Fact:
        if not isinstance(destination, Destination) or version < 1:
            raise Failure(Code.INPUT)
        project = scope.project if destination == Destination.PROJECT else None

        def read(conn: sqlite3.Connection) -> Fact:
            _authorize(conn, scope)
            with open_ledger(conn, self.db.deletion_path()) as ledger:
                if ledger.forgotten(fact_id, scope.owner, project):
                    raise Failure(Code.SCOPE)
            row = conn.execute(_FACT_SELECT + " WHERE f.id=? "
                               "AND f.owner=? AND f.project IS ? AND v.version=?",
                               (fact_id, scope.owner, project, version)).fetchone()
            if row is None:
                raise Failure(Code.SCOPE)
            return Fact(*row[:5], Origin(row[5]), *row[6:])
        fact = await self.db.call(read)
        await self.validate(scope)
        return fact

    async def conversations(self, owner: str, project: str) -> list[tuple[str, str]]:
        return await self.db.call(lambda c: [(r[0], r[1]) for r in c.execute(
            "SELECT c.id,c.title FROM conversations c JOIN projects p ON p.id=c.project "
            "WHERE p.owner=? AND p.id=? ORDER BY c.rowid", (owner, project))])

    async def select(self, owner: str, project: str, generation: int, conversation: str | None = None) -> Scope:
        def select(conn: sqlite3.Connection) -> Scope:
            row = conn.execute("SELECT grant FROM projects WHERE id=? AND owner=?", (project, owner)).fetchone()
            if not row:
                raise Failure(Code.SCOPE)
            key = conversation or uuid4().hex
            if conversation is None:
                conn.execute("INSERT INTO conversations(id,project,title) VALUES(?,?,?)", (key, project, "New conversation"))
            scope = Scope(owner, project, key, row[0], generation)
            _authorize(conn, scope)
            return scope
        return await self.db.call(select, write=conversation is None)

    async def approved_project_root(self, scope: Scope) -> Path:
        def validate(conn: sqlite3.Connection) -> str:
            _authorize(conn, scope)
            return str(conn.execute("SELECT root FROM projects WHERE id=?", (scope.project,)).fetchone()[0])
        return Path(await self.db.call(validate))

    async def validate(self, scope: Scope, *, require_root: bool = False) -> None:
        if require_root:
            path = await self.approved_project_root(scope)
            def check_root() -> None:
                check_local_route(path)
                if not path.is_dir():
                    raise Failure(Code.SCOPE)
            await asyncio.to_thread(check_root)
        # A grant can change while the filesystem check is in flight.
        await self.db.call(lambda conn: _authorize(conn, scope))

    async def lookup(self, scope: Scope, request: UUID, text: str) -> Turn | None:
        def read(conn: sqlite3.Connection) -> Turn | None:
            _authorize(conn, scope)
            return _lookup(conn, scope, request, text)
        return await self.db.call(read)

    async def begin(self, scope: Scope, request: UUID, text: str, digest: str) -> tuple[Turn, bool]:
        def begin(conn: sqlite3.Connection) -> tuple[Turn, bool]:
            _authorize(conn, scope)
            cid = scope.conversation
            existing = _lookup(conn, scope, request, text)
            if existing is not None:
                return existing, False
            turn_id = uuid4().hex
            seq = conn.execute("SELECT COALESCE(MAX(seq),0)+1 FROM messages WHERE conversation=?", (cid,)).fetchone()[0]
            conn.execute("INSERT INTO turns(id,conversation,submission,digest,grant_revision,state) "
                         "VALUES(?,?,?,?,?,'active')", (turn_id, cid, request.hex, digest, scope.grant))
            conn.executemany("INSERT INTO messages VALUES(?,?,?,?,?,?)", [
                (uuid4().hex, cid, turn_id, seq, "user", text),
                (uuid4().hex, cid, turn_id, seq+1, "assistant", "")])
            if seq == 1:
                conn.execute("UPDATE conversations SET title=? WHERE id=?", (" ".join(text.split())[:60], cid))
            return _turn(conn, scope, turn_id), True
        return await self.db.call(begin, write=True)

    async def checkpoint(self, scope: Scope, key: str, ordinal: int, text: str) -> None:
        def update(conn: sqlite3.Connection) -> None:
            _authorize(conn, scope)
            changed = conn.execute("UPDATE turns SET ordinal=? WHERE id=? AND conversation=? AND grant_revision=? "
                                   "AND state='active' AND ordinal<?", (ordinal, key, scope.conversation, scope.grant, ordinal))
            if changed.rowcount:
                conn.execute("UPDATE messages SET content=? WHERE turn=? AND role='assistant'", (text, key))
        await self.db.call(update, write=True)

    async def finish(self, scope: Scope, key: str, state: State, text: str, error: Code | None) -> Turn:
        def finish(conn: sqlite3.Connection) -> Turn | None:
            if not recovery.apply_final(conn, PendingSave(scope, key, state, text, error)):
                return None
            return _turn(conn, scope, key)
        result = await self.db.call(finish, write=True)
        if result is None:
            # Raising inside the actor would roll back the status-only update.
            raise Failure(Code.SCOPE)
        return result

    async def preserve(self, item: PendingSave) -> None:
        await asyncio.to_thread(recovery.preserve, self.db.path, item)

    async def clear_recovery(self, key: str) -> None:
        def remove() -> None:
            recovery.record_path(self.db.path, key).unlink(missing_ok=True)
        await asyncio.to_thread(remove)

    async def history(self, scope: Scope, *, after: int = 0, limit: int = 100,
                      query: str = "") -> list[tuple[int, str, str, str]]:
        def fetch(conn: sqlite3.Connection) -> list[tuple[int, str, str, str]]:
            _authorize(conn, scope)
            return [tuple(r) for r in conn.execute(
                f"SELECT m.seq,m.role,m.content,{_DISPLAY_STATE} FROM messages m JOIN turns t ON t.id=m.turn "
                "WHERE m.conversation=? AND m.seq>? AND instr(lower(m.content),lower(?))>0 ORDER BY m.seq LIMIT ?",
                (scope.conversation, after, query, min(max(1, limit), 500)))]
        return await self.db.call(fetch)

    async def context(self, scope: Scope, budget: int) -> list[ChatMessage]:
        def fetch(conn: sqlite3.Connection) -> list[ChatMessage]:
            _authorize(conn, scope)
            remaining = budget
            pairs: list[list[ChatMessage]] = []
            for r in conn.execute("SELECT u.content,a.content FROM turns t "
                                  "JOIN messages u ON u.turn=t.id AND u.role='user' "
                                  "JOIN messages a ON a.turn=t.id AND a.role='assistant' "
                                  "WHERE t.conversation=? AND t.state='completed' ORDER BY u.seq DESC", (scope.conversation,)):
                cost = len(r[0].encode()) + len(r[1].encode()) + 32
                if cost > remaining:
                    break
                remaining -= cost
                pairs.append([ChatMessage("user", r[0]), ChatMessage("assistant", r[1])])
            return [message for pair in reversed(pairs) for message in pair]
        return await self.db.call(fetch)

