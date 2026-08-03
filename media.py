import base64
import io
import json
import mimetypes
import os
import tempfile
import wave

import numpy
import PIL.Image


MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024
MAX_AUDIO_BYTES = 15 * 1024 * 1024
MAX_REQUEST_BYTES = 64 * 1024 * 1024


def parse_url_list(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        items = value
    else:
        text = str(value).strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                items = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"URL list is not valid JSON: {exc}") from exc
            if not isinstance(items, list):
                raise ValueError("URL JSON must be an array.")
        else:
            items = text.splitlines()
    return [str(item).strip() for item in items if str(item).strip()]


def _validate_image(image):
    width, height = image.size
    if not (256 <= width <= 5760 and 256 <= height <= 5760):
        raise ValueError("Images must have width and height between 256 and 5760 pixels.")
    ratio = width / height
    if not 0.4 <= ratio <= 2.5:
        raise ValueError("Image aspect ratio must be between 0.4 and 2.5.")


def _image_to_uri(image):
    image = image.convert("RGB")
    _validate_image(image)
    with io.BytesIO() as buffer:
        image.save(buffer, format="PNG")
        data = buffer.getvalue()
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds the MiniMax 30 MB limit.")
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def image_batch_to_data_uris(tensor):
    if tensor is None:
        return []
    array = numpy.clip(tensor.detach().cpu().numpy() * 255.0, 0, 255).astype(numpy.uint8)
    return [_image_to_uri(PIL.Image.fromarray(frame)) for frame in array]


def first_image_to_data_uri(tensor):
    items = image_batch_to_data_uris(tensor)
    if not items:
        raise ValueError("IMAGE input is empty.")
    return items[0]


def file_to_data_uri(path, mime_type=None, max_bytes=None):
    size = os.path.getsize(path)
    if max_bytes is not None and size > max_bytes:
        raise ValueError(f"Media file exceeds the {max_bytes // (1024 * 1024)} MB limit.")
    mime_type = mime_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def video_to_data_uri(video):
    if video is None:
        raise ValueError("VIDEO input is required.")
    duration_getter = getattr(video, "get_duration", None)
    if callable(duration_getter):
        duration = float(duration_getter())
        if not 2 <= duration <= 15:
            raise ValueError("Reference video duration must be between 2 and 15 seconds.")
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
        path = handle.name
    try:
        video.save_to(path)
        return file_to_data_uri(path, "video/mp4", MAX_VIDEO_BYTES)
    finally:
        if os.path.exists(path):
            os.remove(path)


def audio_to_data_uri(audio):
    if not isinstance(audio, dict) or "waveform" not in audio or "sample_rate" not in audio:
        raise ValueError("AUDIO input must contain waveform and sample_rate.")
    waveform = audio["waveform"]
    if hasattr(waveform, "detach"):
        waveform = waveform.detach()
    if hasattr(waveform, "cpu"):
        waveform = waveform.cpu()
    if hasattr(waveform, "numpy"):
        waveform = waveform.numpy()
    waveform = numpy.asarray(waveform)
    if waveform.ndim == 3:
        waveform = waveform[0]
    elif waveform.ndim == 1:
        waveform = waveform[numpy.newaxis, :]
    if waveform.ndim != 2 or not waveform.shape[-1]:
        raise ValueError("AUDIO waveform must contain samples.")
    sample_rate = int(audio["sample_rate"])
    if sample_rate <= 0:
        raise ValueError("AUDIO sample_rate must be greater than 0.")
    duration = waveform.shape[-1] / sample_rate
    if not 2 <= duration <= 15:
        raise ValueError("Reference audio duration must be between 2 and 15 seconds.")
    pcm = (numpy.clip(waveform.astype(numpy.float32), -1.0, 1.0).T * 32767).astype(numpy.int16)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        path = handle.name
    try:
        with wave.open(path, "wb") as wav_file:
            wav_file.setnchannels(int(waveform.shape[0]))
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm.tobytes())
        return file_to_data_uri(path, "audio/wav", MAX_AUDIO_BYTES)
    finally:
        if os.path.exists(path):
            os.remove(path)


def validate_prompt(prompt):
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ValueError("prompt is required.")
    if len(prompt) > 7000:
        raise ValueError("prompt must be 7000 characters or fewer.")
    return prompt


def validate_request_size(payload):
    size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if size > MAX_REQUEST_BYTES:
        raise ValueError("MiniMax request body exceeds the 64 MB limit; use public URLs or mm_file:// references.")
