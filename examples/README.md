# Example workflows

Configure `../local.json`, restart ComfyUI, then drag a workflow JSON file onto the canvas.

1. `01_text_to_video.json` — prompt-only 2K generation.
2. `02_first_frame_to_video.json` — first-frame image-to-video.
3. `03_first_last_frame_to_video.json` — first/last-frame transition.
4. `04_multimodal_reference_video.json` — reference-image generation; connect up to 9 numbered image inputs, 3 video inputs, and 3 audio inputs.
5. `05_context_ir_to_video.json` — enhance a prompt with Context IR, then generate a video from the enhanced prompt.
6. `06_768p_regenerate_2k.json` — generate a 768P H3 video and pass its exact request and result URL to 2K regeneration.
7. `07_task_query_and_preview.json` — query an existing task ID and download/preview its result.

Replace placeholder image filenames after importing. No workflow contains an API key.
