import pytest
from pathlib import Path
from nanoscrypt.core.context import ContextBuilder
from nanoscrypt.models.session import Session

def test_context_builder_annotation(tmp_path):
    # Setup tmp workspace files
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    test_file = workspace / "code.py"
    test_file.write_text("print('hello')", encoding="utf-8")
    
    # Instantiate ContextBuilder targeting the tmp workspace
    builder = ContextBuilder(workspace_root=workspace)
    session = Session(id="test_sess", workspace_path=str(workspace))
    
    # Test prompt referencing code.py
    prompt = "Review this file: @code.py and explain it"
    assembled = builder.assemble(prompt, session, [])
    
    assert "=== CURRENT WORKSPACE FILES ===" in assembled
    assert "- code.py" in assembled
    assert "=== REFERENCED FILE CONTENTS ===" in assembled
    assert "--- File: code.py ---" in assembled
    assert "print('hello')" in assembled
