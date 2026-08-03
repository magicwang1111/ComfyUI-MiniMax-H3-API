import json
import os
import urllib.parse

import folder_paths
import requests

from .client import MiniMaxClient, load_config
from .media import (
    audio_to_data_uri,
    first_image_to_data_uri,
    parse_url_list,
    validate_prompt,
    validate_request_size,
    video_to_data_uri,
)


NODE_PREFIX = "MiniMax H3"
NODE_CATEGORY = "MiniMax H3"
MODEL = "MiniMax-H3"
RATIOS = ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]
RESOLUTIONS = ["768P", "2K"]
DURATIONS = [str(value) for value in range(4, 16)]
STATUSES = ["all", "queued", "running", "succeeded", "failed", "cancelled"]
TASK_TYPES = ["all", "generation", "h3_context_ir", "regeneration"]
DEFAULT_VIDEO_FILENAME_PREFIX = "video/MiniMax_%year%%month%%day%_%hour%%minute%%second%"
GENERATION_RATES_CNY_PER_SECOND = {"768P": 0.50, "2K": 0.80}
EXTRA_IMAGE_RATE_CNY = 0.20
CREDITS_PER_CNY = 1000 / 7


def _client():
    return MiniMaxClient(load_config())


def _clean_optional(value):
    value = str(value or "").strip()
    return value or None


def _url_item(media_type, url, role):
    return {"type": media_type, media_type: {"url": url}, "role": role}


def _content_kind(content):
    roles = {item.get("role") for item in content if item.get("role")}
    if roles & {"first_frame", "last_frame"}:
        return "frames"
    if roles & {"reference_image", "reference_video", "reference_audio"}:
        return "reference"
    return "text"


def _normalize_ratio(content, ratio):
    kind = _content_kind(content)
    if kind == "text" and ratio == "adaptive":
        raise ValueError("Text-to-video requires a concrete ratio; adaptive is not allowed.")
    if kind == "frames":
        return "adaptive"
    return ratio


def _task_fields(payload):
    task = payload.get("task") or {}
    content = task.get("content") or {}
    return (
        str(content.get("url") or ""),
        str(content.get("prompt") or ""),
        str(task.get("status") or ""),
        str(task.get("task_type") or ""),
        json.dumps(payload, ensure_ascii=False),
    )


def _submit_and_wait(create_method, payload):
    response = create_method(payload)
    task_id = str(response.get("task_id") or "")
    if not task_id:
        raise RuntimeError("MiniMax create response did not include task_id.")
    final_payload = create_method.__self__.wait_task(task_id)
    return task_id, final_payload


def _create_and_wait(create_method, payload):
    task_id, final_payload = _submit_and_wait(create_method, payload)
    video_url, _, status, _, task_json = _task_fields(final_payload)
    return video_url, task_id, status, task_json


def _generation_cost_summary(payload, fallback_resolution):
    task = payload.get("task") or {}
    usage = task.get("usage") or {}
    resolution = str(task.get("resolution") or fallback_resolution)
    rate = GENERATION_RATES_CNY_PER_SECOND.get(resolution)
    total_seconds = usage.get("total_seconds")
    if total_seconds is None:
        total_seconds = (usage.get("input_seconds") or 0) + (usage.get("output_seconds") or 0)
    if rate is None or not total_seconds:
        return "本次费用：API 未返回可计算的用量"

    image_count = int(usage.get("input_image_count") or 0)
    cost = float(total_seconds) * rate + max(image_count - 5, 0) * EXTRA_IMAGE_RATE_CNY
    credits = cost * CREDITS_PER_CNY
    return f"本次费用：¥{cost:.2f}（约 {credits:.2f} 积分）"


class MiniMaxH3ContentBuilder:
    @classmethod
    def INPUT_TYPES(cls):
        optional = {
            "first_frame": ("IMAGE",),
            "last_frame": ("IMAGE",),
        }
        optional.update({f"image_{index}": ("IMAGE",) for index in range(1, 10)})
        optional.update({f"video_{index}": ("VIDEO",) for index in range(1, 4)})
        optional.update({f"audio_{index}": ("AUDIO",) for index in range(1, 4)})
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("MINIMAX_H3_CONTENT",)
    RETURN_NAMES = ("content",)
    FUNCTION = "build"
    CATEGORY = NODE_CATEGORY

    def build(
        self,
        prompt,
        first_frame=None,
        last_frame=None,
        **kwargs,
    ):
        content = [{"type": "text", "text": validate_prompt(prompt)}]
        reference_images = [kwargs.get(f"image_{index}") for index in range(1, 10)]
        reference_videos = [kwargs.get(f"video_{index}") for index in range(1, 4)]
        reference_audios = [kwargs.get(f"audio_{index}") for index in range(1, 4)]
        frame_inputs = first_frame is not None or last_frame is not None
        reference_inputs = any((
            any(item is not None for item in reference_images),
            any(item is not None for item in reference_videos),
            any(item is not None for item in reference_audios),
        ))

        if frame_inputs and reference_inputs:
            raise ValueError("First/last frames cannot be mixed with reference media.")
        if frame_inputs:
            if first_frame is not None:
                content.append(_url_item("image_url", first_image_to_data_uri(first_frame), "first_frame"))
            if last_frame is not None:
                content.append(_url_item("image_url", first_image_to_data_uri(last_frame), "last_frame"))
            return (content,)

        if not reference_inputs:
            return (content,)
        for image in reference_images:
            if image is not None:
                content.append(_url_item("image_url", first_image_to_data_uri(image), "reference_image"))
        for video in reference_videos:
            if video is not None:
                content.append(_url_item("video_url", video_to_data_uri(video), "reference_video"))
        for audio in reference_audios:
            if audio is not None:
                content.append(_url_item("audio_url", audio_to_data_uri(audio), "reference_audio"))

        image_count = sum(item.get("role") == "reference_image" for item in content)
        video_count = sum(item.get("role") == "reference_video" for item in content)
        audio_count = sum(item.get("role") == "reference_audio" for item in content)
        if image_count > 9:
            raise ValueError("At most 9 reference images are supported.")
        if video_count > 3:
            raise ValueError("At most 3 reference videos are supported.")
        if audio_count > 3:
            raise ValueError("At most 3 reference audios are supported.")
        if not image_count and not video_count:
            raise ValueError("Reference mode requires at least one reference image or video; audio cannot be used alone.")
        return (content,)


class MiniMaxH3GenerateVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "content": ("MINIMAX_H3_CONTENT",),
                "resolution": (RESOLUTIONS, {"default": "2K"}),
                "duration": (DURATIONS, {"default": "5"}),
                "ratio": (RATIOS, {"default": "16:9"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "task_id", "status", "task_json", "request_json")
    FUNCTION = "generate"
    CATEGORY = NODE_CATEGORY

    def generate(self, content, resolution, duration, ratio):
        payload = {
            "model": MODEL,
            "content": content,
            "resolution": resolution,
            "duration": int(duration),
            "ratio": _normalize_ratio(content, ratio),
            "aigc_watermark": False,
        }
        validate_request_size(payload)
        request_json = json.dumps(payload, ensure_ascii=False)
        with _client() as client:
            task_id, final_payload = _submit_and_wait(client.create_video, payload)
        video_url, _, status, _, task_json = _task_fields(final_payload)
        return {
            "ui": {"minimax_h3_cost": [_generation_cost_summary(final_payload, resolution)]},
            "result": (video_url, task_id, status, task_json, request_json),
        }


class MiniMaxH3ContextIR:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "content": ("MINIMAX_H3_CONTENT",),
                "duration": (DURATIONS, {"default": "5"}),
                "ratio": (RATIOS, {"default": "16:9"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "MINIMAX_H3_CONTENT")
    RETURN_NAMES = ("enhanced_prompt", "task_id", "status", "task_json", "enhanced_content")
    FUNCTION = "create"
    CATEGORY = NODE_CATEGORY

    def create(self, content, duration, ratio):
        payload = {
            "model": MODEL,
            "content": content,
            "duration": int(duration),
            "ratio": _normalize_ratio(content, ratio),
        }
        validate_request_size(payload)
        with _client() as client:
            response = client.create_context_ir(payload)
            task_id = str(response.get("task_id") or "")
            if not task_id:
                raise RuntimeError("MiniMax create response did not include task_id.")
            final_payload = client.wait_task(task_id)
        _, prompt, status, _, task_json = _task_fields(final_payload)
        enhanced_content = []
        replaced_prompt = False
        for item in content:
            if item.get("type") == "text" and not replaced_prompt:
                enhanced_content.append({"type": "text", "text": validate_prompt(prompt)})
                replaced_prompt = True
            else:
                enhanced_content.append(item)
        return prompt, task_id, status, task_json, enhanced_content


class MiniMaxH3Regenerate2K:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "generation_request_json": ("STRING", {"forceInput": True}),
                "base_video_url": ("STRING", {"forceInput": True}),
            },
            "optional": {"base_video": ("VIDEO",)},
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "task_id", "status", "task_json")
    FUNCTION = "regenerate"
    CATEGORY = NODE_CATEGORY

    def regenerate(
        self,
        generation_request_json,
        base_video_url,
        base_video=None,
    ):
        try:
            source_request = json.loads(generation_request_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"generation_request_json is not valid JSON: {exc}") from exc
        if source_request.get("model") != MODEL:
            raise ValueError("generation_request_json must use MiniMax-H3.")
        if source_request.get("resolution") != "768P":
            raise ValueError("Video regeneration requires a source request generated at 768P.")
        original_content = source_request.get("content")
        if not isinstance(original_content, list) or not original_content:
            raise ValueError("generation_request_json does not contain valid content.")
        if any(item.get("role") == "base_video" for item in original_content if isinstance(item, dict)):
            raise ValueError("generation_request_json already contains a base_video.")
        if base_video is not None and _clean_optional(base_video_url):
            raise ValueError("Use base_video or base_video_url, not both.")
        if base_video is not None:
            video_url = video_to_data_uri(base_video)
        else:
            video_url = _clean_optional(base_video_url)
        if not video_url:
            raise ValueError("base_video or base_video_url is required.")
        content = list(original_content) + [_url_item("video_url", video_url, "base_video")]
        payload = {
            "model": MODEL,
            "content": content,
            "resolution": "2K",
            "aigc_watermark": False,
        }
        validate_request_size(payload)
        with _client() as client:
            return _create_and_wait(client.create_regeneration, payload)


class MiniMaxH3QueryTask:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"task_id": ("STRING", {"default": ""})}}

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("video_url", "enhanced_prompt", "status", "task_type", "task_json")
    FUNCTION = "query"
    CATEGORY = NODE_CATEGORY

    def query(self, task_id):
        with _client() as client:
            return _task_fields(client.query_task(task_id))


class MiniMaxH3ListTasks:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "page_num": ("INT", {"default": 1, "min": 1, "max": 100000}),
                "page_size": ("INT", {"default": 20, "min": 1, "max": 100}),
                "status": (STATUSES, {"default": "all"}),
                "task_type": (TASK_TYPES, {"default": "all"}),
                "task_ids": ("STRING", {"multiline": True, "default": ""}),
                "model": ("STRING", {"default": MODEL}),
            }
        }

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("items_json", "total")
    FUNCTION = "list"
    CATEGORY = NODE_CATEGORY
    OUTPUT_NODE = True

    def list(self, page_num, page_size, status, task_type, task_ids, model):
        with _client() as client:
            payload = client.list_tasks(
                page_num=page_num,
                page_size=page_size,
                status="" if status == "all" else status,
                task_ids=parse_url_list(task_ids),
                model=_clean_optional(model) or "",
                task_type="" if task_type == "all" else task_type,
            )
        return json.dumps(payload.get("items") or [], ensure_ascii=False), int(payload.get("total") or 0)


class MiniMaxH3CancelDeleteTask:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"task_id": ("STRING", {"default": ""})}}

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("action", "status", "result_json")
    FUNCTION = "cancel_or_delete"
    CATEGORY = NODE_CATEGORY
    OUTPUT_NODE = True

    def cancel_or_delete(self, task_id):
        with _client() as client:
            payload = client.delete_task(task_id)
        return (
            str(payload.get("action") or ""),
            str(payload.get("status") or ""),
            json.dumps(payload, ensure_ascii=False),
        )


def _saved_result(filename, subfolder, folder_type):
    return {"filename": filename, "subfolder": subfolder, "type": folder_type}


def _local_media_url(filename, subfolder, folder_type):
    query = [
        f"type={urllib.parse.quote(str(folder_type), safe='')}",
        f"filename={urllib.parse.quote(str(filename), safe='')}",
    ]
    if subfolder:
        query.append(f"subfolder={urllib.parse.quote(str(subfolder), safe='')}")
    return "/api/view?" + "&".join(query)


class MiniMaxH3PreviewVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_url": ("STRING", {"forceInput": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("file_path",)
    OUTPUT_NODE = True
    FUNCTION = "download"
    CATEGORY = NODE_CATEGORY

    def download(self, video_url):
        video_url = str(video_url or "").strip()
        if not video_url:
            raise ValueError("video_url is required.")
        output_dir = folder_paths.get_output_directory()
        full_output_folder, filename, counter, subfolder, _ = folder_paths.get_save_image_path(
            DEFAULT_VIDEO_FILENAME_PREFIX, output_dir
        )
        os.makedirs(full_output_folder, exist_ok=True)
        file = f"{filename}_{counter:05}_.mp4"
        file_path = os.path.join(full_output_folder, file)
        try:
            with requests.get(video_url, stream=True, timeout=120) as response:
                response.raise_for_status()
                with open(file_path, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
        except Exception:
            if os.path.exists(file_path):
                os.remove(file_path)
            raise
        preview_url = _local_media_url(file, subfolder, "output")
        return {
            "ui": {
                "images": [_saved_result(file, subfolder, "output")],
                "video_url": [preview_url],
                "animated": (True,),
            },
            "result": (file_path,),
        }


NODE_CLASS_MAPPINGS = {
    f"{NODE_PREFIX} Content Builder": MiniMaxH3ContentBuilder,
    f"{NODE_PREFIX} Generate Video": MiniMaxH3GenerateVideo,
    f"{NODE_PREFIX} Context IR": MiniMaxH3ContextIR,
    f"{NODE_PREFIX} Regenerate 2K": MiniMaxH3Regenerate2K,
    f"{NODE_PREFIX} Query Task": MiniMaxH3QueryTask,
    f"{NODE_PREFIX} List Tasks": MiniMaxH3ListTasks,
    f"{NODE_PREFIX} Cancel Delete Task": MiniMaxH3CancelDeleteTask,
    f"{NODE_PREFIX} Preview Video": MiniMaxH3PreviewVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {key: key for key in NODE_CLASS_MAPPINGS}
