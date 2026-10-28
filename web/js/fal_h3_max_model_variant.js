import { app } from "../../../scripts/app.js";

const NODE_ID = "FalH3MaxVideoGH";
const DEFAULT_VARIANT = "H3 Max";
const VARIANTS = [DEFAULT_VARIANT, "H3 Max Turbo"];

export function moveModelWidgetFirst(node) {
    const index = node.widgets?.findIndex(widget => widget.name === "model_variant") ?? -1;
    if (index > 0) node.widgets.unshift(node.widgets.splice(index, 1)[0]);
}

export function migrateModelWidgetValues(info, widgets) {
    // LiteGraph restores positional values before onConfigure. Migrate before
    // calling configure so no widget callback ever observes shifted values.
    // inputs/outputs/links remain exactly as saved, including converted widgets.
    const result = { ...info };
    const values = Array.isArray(info?.widgets_values) ? [...info.widgets_values] : null;
    const named = info?.widgets_values_named;
    const savedVariant = named?.model_variant;
    if (named && typeof named === "object") {
        result.widgets_values_named = { ...named, model_variant: savedVariant ?? DEFAULT_VARIANT };
    }
    if (!values) return result;
    if (["dry_run", "generate"].includes(values[0])) {
        // Accept both pre-V0.2.2 positional workflows and native optional-widget
        // order saved with the model at the end (e.g. before extension reload).
        const trailingVariant = VARIANTS.includes(values.at(-1)) ? values.pop() : DEFAULT_VARIANT;
        values.unshift(savedVariant ?? trailingVariant);
    } else if (values.length === 0) {
        values.push(savedVariant ?? DEFAULT_VARIANT);
    }
    const serializedWidgets = (widgets || []).filter(widget => widget.serialize !== false);
    const controlIndex = serializedWidgets.findIndex(widget => widget.name === "control_after_generate");
    // Some old workflows predate the frontend's automatic seed-control widget.
    if (controlIndex >= 0 && typeof values[controlIndex] === "boolean") {
        values.splice(controlIndex, 0, serializedWidgets[controlIndex].value);
    }
    result.widgets_values = values;
    return result;
}

app.registerExtension({
    name: "HuTX.MiniMaxH3Studio.FalVideo",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_ID) return;
        const originalCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalCreated?.apply(this, arguments);
            moveModelWidgetFirst(this);
            return result;
        };
        const originalConfigure = nodeType.prototype.configure;
        nodeType.prototype.configure = function (info, ...args) {
            moveModelWidgetFirst(this);
            return originalConfigure.call(this, migrateModelWidgetValues(info, this.widgets), ...args);
        };
    },
});
