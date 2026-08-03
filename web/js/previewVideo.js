import { app, ANIM_PREVIEW_WIDGET } from "../../../scripts/app.js";
import { createImageHost } from "../../../scripts/ui/imagePreview.js";

const BASE_SIZE = 640;

function chainCallback(object, property, callback) {
    const original = object[property];
    object[property] = function () {
        if (original) {
            original.apply(this, arguments);
        }
        callback.apply(this, arguments);
    };
}

function addVideoPreview(nodeType) {
    const createVideo = (url) => new Promise((resolve) => {
        const video = document.createElement("video");
        video.addEventListener("loadedmetadata", () => {
            video.controls = false;
            video.loop = true;
            video.muted = true;
            video.autoplay = true;
            video.style.width = "100%";
            video.style.height = "100%";
            video.style.maxWidth = "100%";
            video.style.maxHeight = "100%";
            video.style.objectFit = "contain";
            resolve(video);
        });
        video.addEventListener("error", () => resolve(null));
        video.src = url;
    });

    nodeType.prototype.onDrawBackground = function () {
        if (this.flags.collapsed) {
            return;
        }
        const urls = this.images ?? [];
        if (JSON.stringify(this.displayingImages) === JSON.stringify(urls)) {
            return;
        }
        this.displayingImages = urls;
        if (!urls.length) {
            this.imgs = null;
            return;
        }
        Promise.all(urls.map(createVideo)).then((videos) => {
            this.imgs = videos.filter(Boolean);
            if (!this.imgs.length) {
                return;
            }
            this.animatedImages = true;
            const widgetIndex = this.widgets?.findIndex((widget) => widget.name === ANIM_PREVIEW_WIDGET);
            if (widgetIndex > -1) {
                this.widgets[widgetIndex].options.host.updateImages(this.imgs);
            } else {
                this.size[0] = BASE_SIZE;
                this.size[1] = BASE_SIZE;
                const host = createImageHost(this);
                const widget = this.addDOMWidget(ANIM_PREVIEW_WIDGET, "img", host.el, {
                    host,
                    getHeight: host.getHeight,
                    onDraw: host.onDraw,
                    hideOnZoom: false,
                });
                widget.serializeValue = () => ({ height: BASE_SIZE });
                widget.options.host.updateImages(this.imgs);
            }
            this.imgs.forEach((video) => video.play());
            this.setDirtyCanvas(true, true);
        });
    };

    chainCallback(nodeType.prototype, "onExecuted", function (message) {
        if (message?.video_url) {
            this.images = message.video_url;
            this.setDirtyCanvas(true);
        }
    });
}

app.registerExtension({
    name: "MiniMaxH3VideoPreview",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "MiniMax H3 Preview Video") {
            addVideoPreview(nodeType);
        }
    },
});
