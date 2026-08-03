import { app } from "../../../scripts/app.js";
import { ComfyWidgets } from "../../../scripts/widgets.js";

function getOrCreateCostWidget(node) {
    let widget = node.widgets?.find((item) => item.name === "minimax_h3_cost");
    if (widget) {
        return widget;
    }

    widget = ComfyWidgets.STRING(
        node,
        "minimax_h3_cost",
        ["STRING", { multiline: true }],
        app,
    ).widget;
    widget.inputEl.readOnly = true;
    widget.inputEl.style.border = "none";
    widget.inputEl.style.backgroundColor = "transparent";
    widget.inputEl.style.resize = "none";
    widget.inputEl.style.overflow = "hidden";
    widget.serialize = false;
    return widget;
}

app.registerExtension({
    name: "MiniMaxH3GenerationCost",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "MiniMax H3 Generate Video") {
            return;
        }

        const originalOnExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            originalOnExecuted?.apply(this, arguments);

            const summary = message?.minimax_h3_cost?.[0];
            if (!summary) {
                return;
            }

            const widget = getOrCreateCostWidget(this);
            widget.value = summary;
            const computedSize = this.computeSize();
            this.setSize([Math.max(this.size[0], 400), Math.max(this.size[1], computedSize[1])]);
            this.setDirtyCanvas(true, true);
        };
    },
});
