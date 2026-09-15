def test_pipeline_propose_preserves_failure_as_error(monkeypatch):
    import pipeline
    class FakeControl:
        pass
    def boom(*a, **k):
        raise RuntimeError("Ollama returned HTTP 404")
    monkeypatch.setattr(pipeline, "assess", boom)
    out = pipeline.propose(FakeControl(), {"text": "evidence"})
    assert out["status"] == "error"
    assert "HTTP 404" in out["error"]


def test_ollama_connection_error_is_actionable(monkeypatch):
    import assessor
    import requests
    def boom(*a, **k):
        raise requests.exceptions.ConnectionError("refused")
    monkeypatch.setattr(requests, "post", boom)
    try:
        assessor._ollama("system", "user")
    except RuntimeError as exc:
        msg = str(exc)
        assert "Cannot connect to Ollama" in msg
        assert assessor.OLLAMA_MODEL in msg
    else:
        raise AssertionError("expected actionable Ollama connection error")
