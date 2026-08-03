# ComfyUI MiniMax H3 API

ComfyUI nodes for the MiniMax H3 Video V2 API. The plugin supports text-to-video, first/last-frame video, multimodal reference video, H3-Context-IR, 768P-to-2K regeneration, task management, download, and preview.

## Configuration

Copy `local.example.json` to `local.json` and add your MiniMax API key:

```json
{
  "api_key": "YOUR_MINIMAX_API_KEY",
  "base_url": "https://api.minimaxi.com",
  "poll_interval": 5,
  "request_timeout": 60,
  "max_wait_seconds": 3600
}
```

`local.json` is ignored by Git. The API key is read when a node executes and is never included in workflow files or request outputs.

## Nodes

- **MiniMax H3 Content Builder** builds and validates the multimodal `content` array.
- **MiniMax H3 Generate Video** creates a video task and automatically polls until completion.
- **MiniMax H3 Context IR** creates an asynchronous prompt-enhancement task and returns reusable enhanced content.
- **MiniMax H3 Regenerate 2K** reuses an exact 768P generation request and adds the source video.
- **MiniMax H3 Query Task** queries a task created during the last seven days.
- **MiniMax H3 List Tasks** lists and filters recent tasks.
- **MiniMax H3 Cancel Delete Task** cancels queued tasks or deletes succeeded/failed task records.
- **MiniMax H3 Preview Video** downloads the result as `video/MiniMax_日期_时间.mp4` and scales the preview with the node size.

## Content Builder inputs

- Prompt only creates text-to-video content.
- Connecting `first_frame`, `last_frame`, or both creates frame-guided content and automatically uses the `adaptive` ratio.
- Connecting `image_1`–`image_9`, `video_1`–`video_3`, or `audio_1`–`audio_3` creates reference content. At least one image or video is required.

The content mode is inferred from connected inputs. Native ComfyUI `IMAGE`, `VIDEO`, and `AUDIO` inputs are converted to MiniMax data URIs. The complete JSON request must not exceed 64 MB.

Polling is always enabled. AIGC watermarking is always disabled. These internal settings are not shown in the node UI.

## Regeneration

Generate the source video at `768P`, connect `request_json` from **Generate Video** to `generation_request_json` on **Regenerate 2K**, and provide the exact 768P source video. MiniMax requires the source video to contain audio and match its H3 768P output specification.

## Examples

Import workflow JSON files from `examples/`. See `examples/README.md` for required inputs and usage notes. Example workflows never contain an API key.

## API documentation

- [Create video generation task](https://platform.minimaxi.com/docs/api-reference/video-generation-v2-create)
- [Query task](https://platform.minimaxi.com/docs/api-reference/video-generation-v2-query)
- [List tasks](https://platform.minimaxi.com/docs/api-reference/video-generation-v2-list)
- [Cancel or delete task](https://platform.minimaxi.com/docs/api-reference/video-generation-v2-delete)
- [H3-Context-IR](https://platform.minimaxi.com/docs/api-reference/video-generation-v2-h3-context-ir)
- [Video regeneration](https://platform.minimaxi.com/docs/api-reference/video-generation-v2-regeneration)
