from freeassetfilter.services.ai.context import AIFileContextService

def test_deepseek_vision_data_url(tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(b"png-data")
    part = AIFileContextService().image_content_part(str(path))
    assert part["type"] == "image_url"
    assert str(part["image_url"]["url"]).startswith("data:image/png;base64,")

def test_vision_message_contains_text_and_image(tmp_path):
    path = tmp_path / "image.jpg"
    path.write_bytes(b"jpg-data")
    message = AIFileContextService().vision_message("describe", [str(path)])
    assert message["role"] == "user" and len(message["content"]) == 2
