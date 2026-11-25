import { createHash, randomUUID } from "node:crypto";
import * as vscode from "vscode";

export interface DocumentBase {
    document_uri: string;
    document_id: string;
    document_version: number;
    sha256: string;
}

export class SnapshotCapture {
    private readonly documents = new WeakMap<vscode.TextDocument, string>();

    closed(document: vscode.TextDocument): void {
        this.documents.delete(document);
    }

    base(document: vscode.TextDocument): { workspace_uri: string; base: DocumentBase; original: string } {
        const folder = vscode.workspace.getWorkspaceFolder(document.uri);
        if (document.isClosed || !folder || document.uri.scheme !== "file" || document.uri.authority ||
            folder.uri.scheme !== "file" || folder.uri.authority) {
            throw new Error("Choose a saved local file in the paired workspace folder.");
        }
        const end = document.lineAt(document.lineCount - 1).range.end;
        if (document.offsetAt(end) > 524288) {
            throw new Error("The open document exceeds the editor context size limit.");
        }
        let id = this.documents.get(document);
        if (!id) {
            id = randomUUID().replaceAll("-", "");
            this.documents.set(document, id);
        }
        const original = document.getText();
        return {
            workspace_uri: folder.uri.toString(),
            base: {
                document_uri: document.uri.toString(),
                document_id: id,
                document_version: document.version,
                sha256: createHash("sha256").update(original, "utf8").digest("hex")
            },
            original
        };
    }

    capture(editor: vscode.TextEditor): object {
        const document = editor.document;
        const { workspace_uri, base } = this.base(document);
        const position = (p: vscode.Position) => ({ line: p.line, character: p.character });
        return {
            workspace_uri,
            ...base,
            dirty: document.isDirty,
            selection: { anchor: position(editor.selection.anchor), active: position(editor.selection.active) },
            diagnostics: vscode.languages.getDiagnostics(document.uri).slice(0, 4).map(diagnostic => ({
                start: position(diagnostic.range.start),
                end: position(diagnostic.range.end),
                severity: diagnostic.severity,
                message: Array.from(diagnostic.message.slice(0, 240)).slice(0, 120).join("") || "Diagnostic"
            }))
        };
    }
}
