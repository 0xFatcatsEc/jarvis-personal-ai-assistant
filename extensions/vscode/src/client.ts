import { createConnection, Socket } from "node:net";
import type { DocumentBase } from "./snapshot";

const SIZE_LIMIT = 4096;
const DEADLINE_MS = 5000;
const PREFIX = "\\\\.\\pipe\\stylus-jarvis-editor-";

interface Invitation {
    pipe: string;
    invitation: string;
}

interface Binding {
    project: string;
    conversation: string;
    generation: number;
    grant: number;
}

export interface PatchReport {
    operation: string;
    digest: string;
    workspace_uri: string;
    state: "uncertain" | "settled" | "acknowledged";
    targets: { path: string; outcome: "applied" | "unchanged" | "unresolved" }[];
}

function isReport(value: unknown): value is PatchReport {
    if (!value || typeof value !== "object") {
        return false;
    }
    const report = value as PatchReport;
    return typeof report.operation === "string" && /^[0-9a-f]{32}$/.test(report.operation) &&
        typeof report.digest === "string" && /^[0-9a-f]{64}$/.test(report.digest) &&
        typeof report.workspace_uri === "string" && report.workspace_uri.length <= 1024 &&
        ["uncertain", "settled", "acknowledged"].includes(report.state) &&
        Array.isArray(report.targets) && report.targets.length >= 1 && report.targets.length <= 3 &&
        report.targets.every(target => target && typeof target.path === "string" && target.path.length <= 1024 &&
            target.path.split("/").every(part => part && part !== "." && part !== ".." && !/[\\:]/.test(part)) &&
            ["applied", "unchanged", "unresolved"].includes(target.outcome));
}

function isBinding(value: unknown): value is Binding {
    if (!value || typeof value !== "object" || Object.keys(value).length !== 4) {
        return false;
    }
    const binding = value as Record<string, unknown>;
    return [binding.project, binding.conversation].every(
        id => typeof id === "string" && /^[0-9a-f]{32}$/.test(id)
    ) && [binding.generation, binding.grant].every(
        revision => typeof revision === "number" && Number.isInteger(revision) && revision >= 0 && revision <= 0x7fffffff
    );
}

function parseInvitation(text: string): Invitation {
    if (text.length > 256) {
        throw new Error("Invalid invitation");
    }
    const data = JSON.parse(text);
    if (!data || typeof data.pipe !== "string" || !data.pipe.startsWith(PREFIX) ||
        !/^[0-9a-f]{32}$/.test(data.pipe.slice(PREFIX.length)) ||
        typeof data.invitation !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(data.invitation) ||
        Object.keys(data).length !== 2) {
        throw new Error("Invalid invitation");
    }
    return { pipe: data.pipe, invitation: data.invitation };
}

interface Pending {
    id: number;
    timer: NodeJS.Timeout;
    resolve(data: Record<string, unknown>): void;
    reject(error: Error): void;
}

export class EditorClient {
    private pending: Pending | undefined;
    private buffer = Buffer.alloc(0);
    private sequence = 0;
    private session: string | undefined;
    private binding: Binding | undefined;
    private window: string | undefined;
    private patches = false;

    private constructor(private readonly socket: Socket, onClose: () => void) {
        socket.on("data", (chunk: Buffer) => this.receive(chunk));
        // Close resolves the pending operation with a generic error.
        socket.on("error", () => this.close());
        socket.once("close", () => {
            const pending = this.takePending();
            this.session = undefined;
            this.binding = undefined;
            this.window = undefined;
            this.patches = false;
            this.buffer = Buffer.alloc(0);
            pending?.reject(new Error("Editor connection closed"));
            onClose();
        });
    }

    static async connect(invitation: string, onClose: () => void, window?: string): Promise<EditorClient> {
        const { pipe, invitation: credential } = parseInvitation(invitation);
        const client = new EditorClient(createConnection({ path: pipe }), onClose);
        try {
            const reply = await client.request({ operation: "pair", versions: [1], invitation: credential,
                                                 window, patches: window ? true : undefined });
            if (typeof reply.session !== "string" ||
                !/^[0-9a-f]{32}$/.test(reply.session) || !Array.isArray(reply.capabilities) ||
                reply.capabilities[0] !== "ping") {
                throw new Error("Invalid pairing response");
            }
            const patches = reply.capabilities.length === 3 && reply.capabilities[2] === "patch";
            if ((reply.capabilities.length === 2 || patches) && reply.capabilities[1] === "snapshot" &&
                Object.keys(reply).length === 6 && window && reply.window === window && isBinding(reply.binding)) {
                client.window = window;
                client.binding = reply.binding;
                client.patches = patches;
            } else if (reply.capabilities.length !== 1 || Object.keys(reply).length !== 4) {
                throw new Error("Invalid pairing capability");
            }
            client.session = reply.session;
            return client;
        } catch (error) {
            client.close();
            throw error;
        }
    }

    async ping(): Promise<void> {
        if (!this.session) {
            throw new Error("Editor session is closed");
        }
        const reply = await this.request({ operation: "ping", version: 1, session: this.session });
        if (Object.keys(reply).length !== 3 || reply.ok !== true) {
            this.close();
            throw new Error("Invalid heartbeat response");
        }
    }

    async share(snapshot: object): Promise<void> {
        if (!this.session || !this.window || !this.binding) {
            throw new Error("Pair this window with a selected JARVIS project first.");
        }
        const reply = await this.request({ operation: "snapshot", version: 1, session: this.session,
                                           window: this.window, binding: this.binding, snapshot });
        if (Object.keys(reply).length === 3 && reply.ok === true) {
            return;
        }
        if (Object.keys(reply).length === 4 && reply.ok === false) {
            if (reply.error === "scope" || reply.error === "offline_policy") {
                throw new Error("The workspace or file is outside the approved local project.");
            }
            if (reply.error === "conflict" || reply.error === "busy") {
                throw new Error("This document identity is stale or the session is full. Pair again.");
            }
        }
        this.close();
        throw new Error("Invalid editor context response");
    }

    async previewPatch(proposal: string, digest: string): Promise<void> {
        const reply = await this.patchRequest("preview_patch", { proposal, digest });
        if (reply.digest !== digest || Object.keys(reply).length !== 4) {
            this.close();
            throw new Error("Patch preview digest was not confirmed.");
        }
    }

    async authorizePatch(digest: string, observed: DocumentBase[]): Promise<{expires: number; operation: string}> {
        const reply = await this.patchRequest("authorize_patch", { digest, observed, approved: true });
        const expires = reply.expires_ms;
        const operation = reply.operation_id;
        if (reply.digest !== digest || Object.keys(reply).length !== 6 || typeof expires !== "number" ||
            typeof operation !== "string" || !/^[0-9a-f]{32}$/.test(operation) ||
            !Number.isSafeInteger(expires) || expires <= Date.now() || expires > Date.now() + 2000) {
            this.close();
            throw new Error("Patch approval expired or its digest changed.");
        }
        return {expires, operation};
    }

    async recoverPatch(workspace_uri: string, action: "latest" | "result" | "observe" | "acknowledge",
                       operation?: string, observed?: DocumentBase[]): Promise<PatchReport | null> {
        const { report } = await this.patchRequest("recover_patch", { workspace_uri, action, operation, observed });
        if (report === null && action === "latest") {
            return null;
        }
        if (!isReport(report) || (operation && report.operation !== operation)) {
            this.close();
            throw new Error("Invalid patch report.");
        }
        return report;
    }

    get isConnected(): boolean {
        return !!this.session && !this.socket.destroyed;
    }

    private async patchRequest(operation: string, patch: object): Promise<Record<string, unknown>> {
        if (!this.session || !this.window || !this.binding || !this.patches) {
            throw new Error("Pair with a JARVIS project before reviewing a patch.");
        }
        const reply = await this.request({ operation, version: 1, session: this.session,
                                           window: this.window, binding: this.binding, patch });
        if (reply.ok !== true) {
            if (reply.error === "busy") {
                throw new Error("The patch is blocked. Check STYLUS JARVIS: View and Reconcile Patch Outcome.");
            }
            throw new Error("JARVIS refused this patch. Check the selected project and review a fresh proposal.");
        }
        return reply;
    }

    close(): void {
        this.socket.destroy();
    }

    private request(fields: Record<string, unknown>): Promise<Record<string, unknown>> {
        if (this.pending || this.socket.destroyed || this.sequence >= 0x7fffffff) {
            return Promise.reject(new Error("Editor session unavailable"));
        }
        const id = ++this.sequence;
        const payload = Buffer.from(JSON.stringify({
            ...fields, request_id: id, deadline_ms: Date.now() + DEADLINE_MS
        }));
        if (payload.length > SIZE_LIMIT) {
            return Promise.reject(new Error("The editor context exceeds the 4 KiB message limit."));
        }
        const header = Buffer.alloc(4);
        header.writeUInt32LE(payload.length);
        return new Promise((resolve, reject) => {
            const timer = setTimeout(() => this.close(), DEADLINE_MS);
            this.pending = { id, timer, resolve, reject };
            this.socket.write(Buffer.concat([header, payload]));
        });
    }

    private takePending(): Pending | undefined {
        const pending = this.pending;
        this.pending = undefined;
        if (pending) {
            clearTimeout(pending.timer);
        }
        return pending;
    }

    private receive(chunk: Buffer): void {
        if (!this.pending || this.buffer.length + chunk.length > SIZE_LIMIT + 4) {
            this.close();
            return;
        }
        this.buffer = Buffer.concat([this.buffer, chunk]);
        if (this.buffer.length < 4) {
            return;
        }
        const size = this.buffer.readUInt32LE();
        if (size < 1 || size > SIZE_LIMIT || this.buffer.length > size + 4) {
            this.close();
        } else if (this.buffer.length === size + 4) {
            try {
                const reply = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(this.buffer.subarray(4)));
                if (!reply || reply.version !== 1 || reply.request_id !== this.pending.id) {
                    this.close();
                    return;
                }
                this.buffer = Buffer.alloc(0);
                this.takePending()?.resolve(reply);
            } catch {
                this.close();
            }
        }
    }
}
