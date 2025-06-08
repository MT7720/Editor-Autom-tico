import pytest
import video_processing_logic as vpl


def test_initialize_app():
    result = vpl.initialize_app({"debug": True})
    assert isinstance(result, dict)
    assert result.get("initialized") is True


def test_process_video():
    input_path = "sample_input.mp4"
    output_path = "sample_output.mp4"
    result = vpl.process_video(input_path, output_path)
    assert result["input"] == input_path
    assert result["output"] == output_path
