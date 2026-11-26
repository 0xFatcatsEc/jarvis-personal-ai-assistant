import { createHash } from "node:crypto";
import * as vscode from "vscode";
import { EditorClient, PatchReport } from "./client";
import { DocumentBase, SnapshotCapture } from "./snapshot";

export const PATCH_SCHEME = "stylus-jarvis-patch";
const APPROVE = "Approve and Apply";

interface PatchTarget {
    base: DocumentBase;
    replacement: string;
}

interface Proposal {
    workspace_uri: string;
    targets: PatchTarget[];
}

export interface ReviewedPatch {
    proposal: Proposal;
    serialized: string;
    digest: string;
    documents: vscode.TextDocument[];
    originals: string[];
    opened: Set<number>;
}

function hash(text: string): string {
    return createHash("sha256").update(text, "utf8").digest("hex");
}

export function buildPatch(raw: string, capture: SnapshotCapture): ReviewedPatch {
    if (Buffer.byteLength(raw) > 4096) {
        throw new Error("The clipboard patch exceeds the 4 KiB protocol limit.");
    }
    let entries: unknown;
    try {
        entries = JSON.parse(raw);
    } catch {
        throw new Error("The clipboard must contain a JSON array of open file URIs and replacement text.");
    }
    if (!Array.isArray(entries) || entries.length < 1 || entries.length > 3) {
        throw new Error("A patch must contain one to three open buffers.");
    }
    const documents: vscode.TextDocument[] = [];
    const originals: string[] = [];
    const targets: PatchTarget[] = [];
    let workspace_uri: string | undefined;
    for (const entry of entries) {
        if (!entry || typeof entry !== "object" || Object.keys(entry).length !== 2 ||
            typeof entry.uri !== "string" || typeof entry.replacement !== "string") {
            throw new Error("Each patch target requires exactly a uri and replacement string.");
        }
        let uri: vscode.Uri;
        try {
            uri = /^[A-Za-z]:[\\/]/.test(entry.uri) ? vscode.Uri.file(entry.uri) : vscode.Uri.parse(entry.uri, true);
        } catch {
            throw new Error("Use a local file URI or an absolute Windows path.");
        }
        const document = vscode.workspace.textDocuments.find(item => item.uri.toString() === uri.toString());
        if (!document || documents.includes(document)) {
            throw new Error("Each patch target must be a distinct open local buffer.");
        }
        const captured = capture.base(document);
        if (workspace_uri !== undefined && workspace_uri !== captured.workspace_uri) {
            throw new Error("All targets must belong to the same approved workspace folder.");
        }
        workspace_uri = captured.workspace_uri;
        const lineEnding = document.eol === vscode.EndOfLine.CRLF ? "\r\n" : "\n";
        const replacement = entry.replacement.replace(/\r\n|\r|\n/g, lineEnding);
        if (replacement === captured.original) {
            throw new Error("Every target must have a change to review.");
        }
        documents.push(document);
        originals.push(captured.original);
        targets.push({ base: captured.base, replacement });
    }
    const proposal = { workspace_uri: workspace_uri!, targets };
    const serialized = JSON.stringify(proposal);
    return { proposal, serialized, digest: hash(serialized), documents, originals, opened: new Set() };
}

function checkedBases(review: ReviewedPatch, capture: SnapshotCapture): DocumentBase[] {
    if (vscode.env.remoteName || !vscode.workspace.isTrusted ||
        JSON.stringify(review.proposal) !== review.serialized || hash(review.serialized) !== review.digest) {
        throw new Error("Workspace trust or the reviewed patch changed.");
    }
    return review.documents.map((document, index) => {
        const current = capture.base(document);
        const expected = review.proposal.targets[index].base;
        if (current.workspace_uri !== review.proposal.workspace_uri ||
            JSON.stringify(current.base) !== JSON.stringify(expected)) {
            throw new Error("An open buffer changed. Review a fresh patch.");
        }
        return current.base;
    });
}

export async function applyPatch(review: ReviewedPatch, client: EditorClient, capture: SnapshotCapture,
                                 current: () => boolean): Promise<PatchReport> {
    if (!current() || !client.isConnected) {
        throw new Error("This editor session changed. Review a fresh patch.");
    }
    const permit = await client.authorizePatch(review.digest, checkedBases(review, capture));
    let dispatched = false;
    let failure: unknown;
    try {
        checkedBases(review, capture);
        const edit = new vscode.WorkspaceEdit();
        for (const [index, document] of review.documents.entries()) {
            const end = document.lineAt(document.lineCount - 1).range.end;
            edit.replace(document.uri, new vscode.Range(new vscode.Position(0, 0), end),
                         review.proposal.targets[index].replacement);
        }
        if (!current() || !client.isConnected || Date.now() >= permit.expires) {
            throw new Error("The editor approval expired. Review a fresh patch.");
        }
        dispatched = true;
        await vscode.workspace.applyEdit(edit);
    } catch (error) {
        if (dispatched) {
            throw new Error("The edit outcome is unresolved. Use View and Reconcile Patch Outcome.");
        }
        failure = error;
    }
    try {
        if (!current() || !client.isConnected) {
            throw new Error("Session changed.");
        }
        const observed = observeOpenDocuments(review.documents, review.proposal.workspace_uri, capture);
        const report = await client.recoverPatch(review.proposal.workspace_uri, "result", permit.operation, observed);
        if (report && !failure) {
            return report;
        }
    } catch {
        // The durable operation remains inspectable after re-pairing.
    }
    throw new Error(failure instanceof Error
        ? `${failure.message} Inspect the outcome with View and Reconcile Patch Outcome.`
        : "The edit receipt is unavailable. Use View and Reconcile Patch Outcome after pairing.");
}

function observeOpenDocuments(documents: readonly vscode.TextDocument[], workspace: string,
                              capture: SnapshotCapture): DocumentBase[] {
    const observations: DocumentBase[] = [];
    for (const document of documents) {
        try {
            const observed = capture.base(document);
            if (observed.workspace_uri === workspace) {
                observations.push(observed.base);
            }
        } catch {
            // Closed or unsupported buffers remain unresolved.
        }
    }
    return observations;
}

function reportDetail(report: PatchReport): string {
    return report.targets.map(target => `${target.path} — ${target.outcome}`).join("\n");
}

function showReport(report: PatchReport): void {
    const title = report.state === "uncertain" ? "Patch outcome needs review"
        : report.state === "acknowledged" ? "Unresolved patch outcome acknowledged" : "Patch outcome recorded";
    void vscode.window.showInformationMessage(title, { modal: true, detail: reportDetail(report) });
}

export class PatchReview implements vscode.TextDocumentContentProvider {
    private review: ReviewedPatch | undefined;
    private readonly content = new Map<string, string>();

    constructor(private readonly capture: SnapshotCapture,
                private readonly confirm: (detail: string) => PromiseLike<boolean> = async detail =>
                    await vscode.window.showWarningMessage("Apply this reviewed patch to open buffers?",
                                                           { modal: true, detail }, APPROVE) === APPROVE) {}

    provideTextDocumentContent(uri: vscode.Uri): string {
        return this.content.get(uri.toString()) ?? "";
    }

    clear(): void {
        this.review = undefined;
        this.content.clear();
    }

    async preview(client: EditorClient, current: () => boolean, raw: string): Promise<void> {
        this.clear();
        const review = buildPatch(raw, this.capture);
        if (!current()) {
            throw new Error("The editor session changed.");
        }
        await client.previewPatch(review.serialized, review.digest);
        if (!current()) {
            throw new Error("The editor session changed.");
        }
        this.review = review;
        await this.openDiffFor(0);
    }

    async chooseDiff(): Promise<void> {
        const review = this.review;
        if (!review) {
            throw new Error("Start a patch review first.");
        }
        const item = await vscode.window.showQuickPick(review.documents.map((document, index) => ({
            label: document.uri.fsPath,
            description: review.opened.has(index) ? "Diff opened" : "Diff pending",
            index
        })), { placeHolder: "Select a target to inspect its exact change" });
        if (item && this.review === review) {
            await this.openDiffFor(item.index);
        }
    }

    async openDiffFor(index: number): Promise<void> {
        const review = this.review;
        if (!review || !review.documents[index] ||
            hash(review.originals[index]) !== review.proposal.targets[index].base.sha256) {
            throw new Error("The preview target is unavailable.");
        }
        const before = vscode.Uri.from({ scheme: PATCH_SCHEME, path: `/${review.digest}/${index}/before` });
        const after = vscode.Uri.from({ scheme: PATCH_SCHEME, path: `/${review.digest}/${index}/after` });
        this.content.set(before.toString(), review.originals[index]);
        this.content.set(after.toString(), review.proposal.targets[index].replacement);
        await vscode.commands.executeCommand("vscode.diff", before, after,
            `JARVIS review · ${review.documents[index].uri.fsPath}`, { preview: false });
        if (this.review === review) {
            review.opened.add(index);
        }
    }

    async approve(client: EditorClient, current: () => boolean,
                  exclusive: (action: () => Promise<void>) => Promise<void>): Promise<void> {
        const review = this.review;
        if (!review || review.opened.size !== review.documents.length) {
            throw new Error("Open every target's diff before approving the patch.");
        }
        const detail = `Workspace: ${review.proposal.workspace_uri}\nDigest: ${review.digest}\n\n` +
            review.documents.map(document => document.uri.fsPath).join("\n");
        if (!await this.confirm(detail)) {
            return;
        }
        if (this.review !== review) {
            throw new Error("The pending patch changed. Review the new patch.");
        }
        try {
            await exclusive(async () => showReport(await applyPatch(review, client, this.capture,
                                                                    () => current() && this.review === review)));
        } finally {
            if (this.review === review) {
                this.clear();
            }
        }
    }

    async recover(client: EditorClient, current: () => boolean,
                  exclusive: <T>(action: () => Promise<T>) => Promise<T>, acknowledge: boolean): Promise<void> {
        const active = vscode.window.activeTextEditor?.document.uri;
        const folder = (active && vscode.workspace.getWorkspaceFolder(active)) ??
            (vscode.workspace.workspaceFolders?.length === 1 ? vscode.workspace.workspaceFolders[0] : undefined);
        if (!folder || folder.uri.scheme !== "file" || folder.uri.authority) {
            throw new Error("Select a file in the approved local workspace.");
        }
        const workspace = folder.uri.toString();
        const observed = await exclusive(async () => {
            if (!current()) {
                throw new Error("The editor session changed.");
            }
            const report = await client.recoverPatch(workspace, "latest");
            if (!current()) {
                throw new Error("The editor session changed.");
            }
            if (report?.state !== "uncertain") {
                return report;
            }
            const targetPaths = new Set(report.targets.map(target =>
                vscode.Uri.joinPath(folder.uri, ...target.path.split("/")).toString()));
            const documents = vscode.workspace.textDocuments.filter(document => targetPaths.has(document.uri.toString()));
            return await client.recoverPatch(workspace, "observe", report.operation,
                                              observeOpenDocuments(documents, workspace, this.capture));
        });
        if (!current()) {
            throw new Error("The editor session changed.");
        }
        if (!observed) {
            void vscode.window.showInformationMessage("There is no recorded patch for this workspace.");
            return;
        }
        if (!acknowledge || observed.state !== "uncertain") {
            showReport(observed);
            return;
        }
        const confirm = "Acknowledge Unresolved Targets";
        const detail = reportDetail(observed) +
            "\n\nInspect unresolved buffers first. Acknowledgment allows a fresh patch review. It does not edit buffers.";
        if (await vscode.window.showWarningMessage("Acknowledge the remaining uncertainty?",
                                                   { modal: true, detail }, confirm) !== confirm) {
            return;
        }
        await exclusive(async () => {
            if (!current()) {
                throw new Error("The editor session changed.");
            }
            const acknowledged = await client.recoverPatch(workspace, "acknowledge", observed.operation);
            if (acknowledged) {
                showReport(acknowledged);
            }
        });
    }
}
