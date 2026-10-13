from pathlib import Path
from freeassetfilter.services.ai.context import AIFileContextService, render_file_context

def test_text_context_budget(tmp_path: Path):
    path = tmp_path / "a.md"
    path.write_text("abcdef", encoding="utf-8")
    item = AIFileContextService(max_chars=3, total_chars=3).extract([str(path)])[0]
    assert item.text == "abc" and item.truncated
    assert "文件: a.md" in render_file_context([item])
