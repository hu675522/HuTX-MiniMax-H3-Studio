export class FalPromptTimingState {
    constructor() {
        this.pendingQueueStarts = [];
        this.activeQueueStart = null;
        // A prompt owns a separate node map, so reusing the same Fal node in
        // consecutive queues cannot overwrite an earlier prompt's timestamp.
        this.promptNodes = new Map();
    }

    recordQueueStart(queueStartedAtMs, batchCount = 1) {
        this.prune(queueStartedAtMs);
        this.pendingQueueStarts.push({
            queueStartedAtMs,
            createdAtMs: queueStartedAtMs,
            remaining: Math.max(1, Number(batchCount) || 1),
        });
    }

    claimQueueStart() {
        if (!this.activeQueueStart || this.activeQueueStart.remaining <= 0) {
            // ComfyUI consumes pending queue requests in LIFO order.
            this.activeQueueStart = this.pendingQueueStarts.pop() ?? null;
        }
        return this.activeQueueStart;
    }

    finishQueueAttempt() {
        if (!this.activeQueueStart) return;
        this.activeQueueStart.remaining -= 1;
        if (this.activeQueueStart.remaining <= 0) this.activeQueueStart = null;
    }

    associatePrompt(promptId, nodeIds, queueStart) {
        if (!promptId || !queueStart) return;
        const promptKey = String(promptId);
        const nodes = this.promptNodes.get(promptKey) ?? new Map();
        for (const nodeId of nodeIds) {
            nodes.set(String(nodeId), {
                queueStartedAtMs: queueStart.queueStartedAtMs,
                createdAtMs: queueStart.createdAtMs,
            });
        }
        if (nodes.size) this.promptNodes.set(promptKey, nodes);
    }

    findPromptNode(promptId, nodeIds) {
        const nodes = this.promptNodes.get(String(promptId));
        if (!nodes) return null;
        for (const nodeId of nodeIds) {
            const timing = nodes.get(String(nodeId));
            if (timing) return timing;
        }
        return null;
    }

    cleanupPrompt(promptId) {
        if (promptId == null) return false;
        return this.promptNodes.delete(String(promptId));
    }

    prune(nowMs = Date.now(), maxAgeMs = 24 * 60 * 60 * 1000) {
        const oldestAllowed = nowMs - maxAgeMs;
        this.pendingQueueStarts = this.pendingQueueStarts.filter(
            (item) => item.createdAtMs >= oldestAllowed,
        );
        if (this.activeQueueStart?.createdAtMs < oldestAllowed) this.activeQueueStart = null;
        for (const [promptId, nodes] of this.promptNodes) {
            const newest = Math.max(...[...nodes.values()].map((item) => item.createdAtMs));
            if (newest < oldestAllowed) this.promptNodes.delete(promptId);
        }
    }

    get promptCount() {
        return this.promptNodes.size;
    }
}
