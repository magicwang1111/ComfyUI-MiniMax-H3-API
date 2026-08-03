import json

import numpy
import pytest

import minimax_test_media as media
import minimax_test_nodes as nodes


class FakeImageTensor:
    def __init__(self, array):
        self.array = array

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.array


def test_parse_url_list_lines_and_json():
    assert media.parse_url_list("https://a\nhttps://b") == ["https://a", "https://b"]
    assert media.parse_url_list('["mm_file://1", "mm_file://2"]') == ["mm_file://1", "mm_file://2"]


def test_image_to_data_uri_and_dimensions():
    image = FakeImageTensor(numpy.zeros((1, 256, 256, 3), dtype=numpy.float32))
    assert media.first_image_to_data_uri(image).startswith("data:image/png;base64,")
    with pytest.raises(ValueError, match="between 256 and 5760"):
        media.first_image_to_data_uri(FakeImageTensor(numpy.zeros((1, 128, 128, 3), dtype=numpy.float32)))


def test_request_size_limit(monkeypatch):
    monkeypatch.setattr(media, "MAX_REQUEST_BYTES", 20)
    with pytest.raises(ValueError, match="64 MB"):
        media.validate_request_size({"content": "x" * 100})


def test_text_content_and_ratio_validation():
    content = nodes.MiniMaxH3ContentBuilder().build("hello")[0]
    assert content == [{"type": "text", "text": "hello"}]
    with pytest.raises(ValueError, match="concrete ratio"):
        nodes._normalize_ratio(content, "adaptive")


def test_frame_content_forces_adaptive_ratio():
    frame = FakeImageTensor(numpy.zeros((1, 256, 256, 3), dtype=numpy.float32))
    content = nodes.MiniMaxH3ContentBuilder().build(
        "move",
        first_frame=frame,
    )[0]
    assert content[1]["role"] == "first_frame"
    assert nodes._normalize_ratio(content, "16:9") == "adaptive"


def test_reference_audio_cannot_be_used_alone():
    audio = {"waveform": numpy.zeros((1, 1, 20), dtype=numpy.float32), "sample_rate": 10}
    with pytest.raises(ValueError, match="audio cannot be used alone"):
        nodes.MiniMaxH3ContentBuilder().build("speak", audio_1=audio)


def test_content_builder_exposes_numbered_reference_inputs():
    input_types = nodes.MiniMaxH3ContentBuilder.INPUT_TYPES()
    assert list(input_types["required"]) == ["prompt"]
    optional = input_types["optional"]
    assert list(optional)[:2] == ["first_frame", "last_frame"]
    assert [name for name in optional if name.startswith("image_")] == [f"image_{index}" for index in range(1, 10)]
    assert [name for name in optional if name.startswith("video_")] == [f"video_{index}" for index in range(1, 4)]
    assert [name for name in optional if name.startswith("audio_")] == [f"audio_{index}" for index in range(1, 4)]
    assert len(optional) == 17


def test_numbered_reference_images_keep_their_order():
    black = FakeImageTensor(numpy.zeros((1, 256, 256, 3), dtype=numpy.float32))
    white = FakeImageTensor(numpy.ones((1, 256, 256, 3), dtype=numpy.float32))
    content = nodes.MiniMaxH3ContentBuilder().build("move", image_1=black, image_2=white)[0]
    references = [item for item in content if item.get("role") == "reference_image"]
    assert len(references) == 2
    assert references[0]["image_url"]["url"] != references[1]["image_url"]["url"]


class FakeClient:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def create_video(self, payload):
        self.payload = payload
        return {"task_id": "task-1"}

    def wait_task(self, task_id):
        return {
            "task": {
                "id": task_id,
                "status": "succeeded",
                "task_type": "generation",
                "content": {"url": "https://cdn/result.mp4"},
                "resolution": "2K",
                "usage": {"total_seconds": 5, "input_image_count": 0},
            }
        }


def test_generate_node_builds_payload(monkeypatch, capsys):
    fake = FakeClient()
    monkeypatch.setattr(nodes, "_client", lambda: fake)
    content = [{"type": "text", "text": "hello"}]
    response = nodes.MiniMaxH3GenerateVideo().generate(content, "2K", 5, "16:9")
    result = response["result"]
    assert result[:3] == ("https://cdn/result.mp4", "task-1", "succeeded")
    assert json.loads(result[4])["resolution"] == "2K"
    assert response["ui"]["minimax_h3_cost"] == ["本次费用：¥4.00（约 571.43 积分）"]
    assert fake.payload["ratio"] == "16:9"
    assert fake.payload["aigc_watermark"] is False
    assert "[MiniMax H3] task_id=task-1" in capsys.readouterr().out


def test_generation_cost_includes_reference_video_and_extra_images():
    payload = {
        "task": {
            "resolution": "768P",
            "usage": {"input_seconds": 3, "output_seconds": 5, "input_image_count": 7},
        }
    }
    assert nodes._generation_cost_summary(payload, "2K") == "本次费用：¥4.40（约 628.57 积分）"


def test_regeneration_rejects_non_768p_request():
    request_json = json.dumps({"model": "MiniMax-H3", "resolution": "2K", "content": [{"type": "text", "text": "x"}]})
    with pytest.raises(ValueError, match="768P"):
        nodes.MiniMaxH3Regenerate2K().regenerate(request_json, "https://cdn/base.mp4")


def test_polling_is_always_enabled_and_not_exposed_as_an_input():
    for node_class in (nodes.MiniMaxH3GenerateVideo, nodes.MiniMaxH3ContextIR, nodes.MiniMaxH3Regenerate2K):
        input_types = node_class.INPUT_TYPES()
        assert "wait_for_completion" not in input_types["required"]
        assert "callback_url" not in input_types.get("optional", {})


def test_aigc_watermark_is_disabled_and_not_exposed():
    assert "aigc_watermark" not in nodes.MiniMaxH3GenerateVideo.INPUT_TYPES()["required"]
    assert "aigc_watermark" not in nodes.MiniMaxH3Regenerate2K.INPUT_TYPES()["required"]


class FakeContextClient(FakeClient):
    def create_context_ir(self, payload):
        self.payload = payload
        return {"task_id": "context-1"}

    def wait_task(self, task_id):
        return {"task": {"id": task_id, "status": "succeeded", "task_type": "h3_context_ir", "content": {"prompt": "enhanced prompt"}}}


def test_context_ir_returns_content_with_replaced_prompt(monkeypatch):
    fake = FakeContextClient()
    monkeypatch.setattr(nodes, "_client", lambda: fake)
    source_content = [{"type": "text", "text": "original"}, {"type": "image_url", "image_url": {"url": "mm_file://1"}, "role": "reference_image"}]
    result = nodes.MiniMaxH3ContextIR().create(source_content, 5, "adaptive")
    assert result[0] == "enhanced prompt"
    assert result[4][0] == {"type": "text", "text": "enhanced prompt"}
    assert result[4][1] is source_content[1]


def test_preview_uses_hidden_default_filename():
    required = nodes.MiniMaxH3PreviewVideo.INPUT_TYPES()["required"]
    assert list(required) == ["video_url"]
    assert nodes.DEFAULT_VIDEO_FILENAME_PREFIX.startswith("video/MiniMax_%year%")


def test_duration_is_a_four_to_fifteen_second_list():
    expected = [str(value) for value in range(4, 16)]
    for node_class in (nodes.MiniMaxH3GenerateVideo, nodes.MiniMaxH3ContextIR):
        duration = node_class.INPUT_TYPES()["required"]["duration"]
        assert duration[0] == expected
        assert duration[1]["default"] == "5"
