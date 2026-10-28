import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { FalPromptTimingState } from "./fal_h3_max_timing_state.js";

const FAL_NODE_ID = "FalH3MaxVideoGH";
const INSTALL_MARK = Symbol.for("HuTX.MiniMaxH3Studio.Timing.installed");
const timingState = new FalPromptTimingState();
const elapsedByNode = new WeakMap();

function promptContainsFalNode(promptData) {
    const output = promptData?.output;
    if (!output || typeof output !== "object") return { hasFal: false, nodeIds: [] };
    const nodeIds = Object.entries(output)
        .filter(([, value]) => value?.class_type === FAL_NODE_ID)
        .map(([nodeId]) => String(nodeId));
    return { hasFal: nodeIds.length > 0, nodeIds };
}

function graphNode(nodeId) {
    if (nodeId == null) return null;
    return app.graph?.getNodeById?.(nodeId)
        ?? app.graph?.getNodeById?.(Number(nodeId))
        ?? null;
}

function recordVideoReady(event) {
    const detail = event?.detail;
    const promptId = detail?.prompt_id;
    const executedIds = [detail?.display_node, detail?.node]
        .filter((value) => value != null)
        .map(String);
    const timing = timingState.findPromptNode(promptId, executedIds);
    if (!timing) return;
    const node = graphNode(detail?.display_node) ?? graphNode(detail?.node);
    if (!node || (node.comfyClass !== FAL_NODE_ID && node.type !== FAL_NODE_ID)) return;

    const elapsedSeconds = Math.max(0, (Date.now() - timing.queueStartedAtMs) / 1000);
    elapsedByNode.set(node, elapsedSeconds);
    node.setDirtyCanvas?.(true, true);
    console.info(
        `[HuTX H3 Studio] Timing\nworkflow total: ${elapsedSeconds.toFixed(3)}s\n`
        + `definition: promptQueueing -> Fal VIDEO-ready executed event\nprompt_id: ${promptId}`,
    );
}

function clearPromptTiming(event) {
    const promptId = event?.detail?.prompt_id;
    if (promptId) timingState.cleanupPrompt(promptId);
}

function installEventTiming() {
    if (api[INSTALL_MARK]) return;
    api[INSTALL_MARK] = true;

    api.addEventListener("promptQueueing", (event) => {
        const batchCount = Math.max(1, Number(event?.detail?.batchCount) || 1);
        timingState.recordQueueStart(Date.now(), batchCount);
    });

    const originalQueuePrompt = api.queuePrompt;
    api.queuePrompt = async function (...args) {
        const queueStart = timingState.claimQueueStart();
        const promptData = args[1];
        const { hasFal, nodeIds } = promptContainsFalNode(promptData);
        try {
            const response = await originalQueuePrompt.apply(this, args);
            if (queueStart && hasFal && response?.prompt_id) {
                timingState.associatePrompt(response.prompt_id, nodeIds, queueStart);
            }
            return response;
        } finally {
            timingState.finishQueueAttempt();
        }
    };

    api.addEventListener("executed", recordVideoReady);
    api.addEventListener("execution_error", clearPromptTiming);
    api.addEventListener("execution_interrupted", clearPromptTiming);
    api.addEventListener("execution_success", clearPromptTiming);
}

app.registerExtension({
    name: "HuTX.MiniMaxH3Studio.Timing",

    setup() {
        installEventTiming();
    },

    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== FAL_NODE_ID) return;
        const originalDrawForeground = nodeType.prototype.onDrawForeground;
        nodeType.prototype.onDrawForeground = function (ctx) {
            originalDrawForeground?.apply(this, arguments);
            const elapsedSeconds = elapsedByNode.get(this);
            if (!Number.isFinite(elapsedSeconds)) return;

            const label = `Queue → VIDEO: ${elapsedSeconds.toFixed(2)}s`;
            ctx.save();
            ctx.font = "11px sans-serif";
            ctx.textAlign = "right";
            ctx.textBaseline = "middle";
            const width = ctx.measureText(label).width + 10;
            ctx.fillStyle = "rgba(10, 18, 14, 0.82)";
            ctx.fillRect(this.size[0] - width - 4, -20, width, 16);
            ctx.fillStyle = "#a8f0bc";
            ctx.fillText(label, this.size[0] - 9, -12);
            ctx.restore();
        };
    },
});
