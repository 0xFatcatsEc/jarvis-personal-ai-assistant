import { randomUUID } from "node:crypto";
import * as vscode from "vscode";
import { EditorClient } from "./client";
import { PATCH_SCHEME, PatchReview } from "./patch";
import { SnapshotCapture } from "./snapshot";

export function activate(context: vscode.ExtensionContext): void {
    let client: EditorClient | undefined;
    let heartbeat: NodeJS.Timeout | undefined;
    let pendingHeartbeat: Promise<void> | undefined;
    let sharing = false;
    const window = randomUUID().replaceAll("-", "");
    const capture = new SnapshotCapture();
    const patches = new PatchReview(capture);
    let generation = 0;
    const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left);
    status.text = "JARVIS paired";
    status.command = "stylusJarvis.disconnect";

    function disconnect(): void {
        generation++;
        if (heartbeat) {
            clearInterval(heartbeat);
        }
        client?.close();
        client = undefined;
        patches.clear();
        status.hide();
    }

    async function exclusive<T>(action: () => Promise<T>): Promise<T> {
        if (sharing) {
            throw new Error("An editor request is already in progress.");
        }
        sharing = true;
        try {
            await pendingHeartbeat;
            return await action();
        } finally {
            sharing = false;
        }
    }

    async function patchCommand(action: (peer: EditorClient, current: () => boolean) => Promise<void>): Promise<void> {
        const paired = client;
        const current = () => !!paired && client === paired && vscode.workspace.isTrusted && !vscode.env.remoteName;
        try {
            if (!paired || !current()) {
                throw new Error("Pair a trusted local VS Code window with JARVIS first.");
            }
            await action(paired, current);
        } catch (error) {
            void vscode.window.showErrorMessage(error instanceof Error ? error.message : "Patch review failed.");
        }
    }

    context.subscriptions.push(status, { dispose: disconnect },
        vscode.workspace.registerTextDocumentContentProvider(PATCH_SCHEME, patches),
        vscode.workspace.onDidCloseTextDocument(document => capture.closed(document)),
        vscode.commands.registerCommand("stylusJarvis.disconnect", disconnect),
        vscode.commands.registerCommand("stylusJarvis.previewPatch", () =>
            patchCommand((peer, current) => exclusive(async () =>
                patches.preview(peer, current, await vscode.env.clipboard.readText())))),
        vscode.commands.registerCommand("stylusJarvis.choosePatchDiff", () =>
            patchCommand(() => patches.chooseDiff())),
        vscode.commands.registerCommand("stylusJarvis.approvePatch", () =>
            patchCommand((peer, current) => patches.approve(peer, current, exclusive))),
        vscode.commands.registerCommand("stylusJarvis.reconcilePatch", () =>
            patchCommand((peer, current) => patches.recover(peer, current, exclusive, false))),
        vscode.commands.registerCommand("stylusJarvis.acknowledgePatch", () =>
            patchCommand((peer, current) => patches.recover(peer, current, exclusive, true))),
        vscode.commands.registerCommand("stylusJarvis.shareContext", async () => {
            const paired = client;
            if (!paired || vscode.env.remoteName || !vscode.workspace.isTrusted) {
                void vscode.window.showErrorMessage("Pair a trusted local VS Code window with JARVIS first.");
                return;
            }
            try {
                await exclusive(async () => {
                    const editor = vscode.window.activeTextEditor;
                    if (!editor || client !== paired || vscode.env.remoteName || !vscode.workspace.isTrusted) {
                        throw new Error("Select a file in the paired VS Code window.");
                    }
                    await paired.share(capture.capture(editor));
                });
                vscode.window.setStatusBarMessage("Editor context shared with JARVIS", 2500);
            } catch (error) {
                void vscode.window.showErrorMessage(error instanceof Error ? error.message : "Context sharing failed.");
            }
        }),
        vscode.commands.registerCommand("stylusJarvis.pair", async () => {
            if (process.platform !== "win32" || vscode.env.remoteName || !vscode.workspace.isTrusted) {
                void vscode.window.showErrorMessage("Pairing requires a trusted local Windows VS Code window.");
                return;
            }
            const invitation = await vscode.window.showInputBox({
                prompt: "Paste the one-time invitation from JARVIS",
                password: true
            });
            if (!invitation) {
                return;
            }
            disconnect();
            const attempt = generation;
            try {
                const paired = await EditorClient.connect(invitation, () => {
                    if (generation === attempt && client) {
                        disconnect();
                    }
                }, window);
                if (generation !== attempt) {
                    paired.close();
                    return;
                }
                client = paired;
                status.show();
                heartbeat = setInterval(() => {
                    if (sharing || pendingHeartbeat) {
                        return;
                    }
                    pendingHeartbeat = paired.ping().catch(() => {
                        if (generation === attempt) {
                            disconnect();
                        }
                    }).finally(() => {
                        pendingHeartbeat = undefined;
                    });
                }, 10000);
            } catch {
                if (generation === attempt) {
                    void vscode.window.showErrorMessage("Pairing failed. Request a fresh invitation in JARVIS.");
                }
            }
        })
    );
}
