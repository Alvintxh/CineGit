import base64
import io

import httpx
import pytest
from PIL import Image

from cinegit.engine import Engine
from cinegit.service import demo_workflow


def test_remote_image_contract_and_secret_separation(tmp_path, monkeypatch):
    monkeypatch.setenv("CINEGIT_PROVIDER_URL", "https://gateway.example/generate")
    monkeypatch.setenv("CINEGIT_PROVIDER_TOKEN", "test-secret")
    monkeypatch.setenv("CINEGIT_PROVIDER_MODEL", "flux-fixture")
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), (200, 50, 10)).save(buffer, format="PNG")
    received = []

    def respond(request):
        import json
        received.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer test-secret"
        return httpx.Response(200, json={"base64": base64.b64encode(buffer.getvalue()).decode()})

    client_class = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **options: client_class(transport=httpx.MockTransport(respond), **options))
    engine = Engine(tmp_path)
    workflow = demo_workflow()
    workflow["nodes"][0]["mcp_tool"] = "mcp_image_gen"
    plan = engine.plan(workflow)
    generated = engine.render_node(plan[0], {})
    assert generated["fallback"] is False
    assert received[0]["tool"] == "mcp_image_gen"
    assert received[0]["model"] == "flux-fixture"
    assert "{{" not in received[0]["prompt"]
    with Image.open(tmp_path / generated["artifact"].removeprefix("/media/")) as image:
        assert image.size == (1280, 720)
        assert image.format == "WEBP"
    assert "test-secret" not in str(plan)
    monkeypatch.setenv("CINEGIT_PROVIDER_TOKEN", "rotated-secret")
    assert Engine(tmp_path).plan(workflow)[0]["node_hash"] == plan[0]["node_hash"]


def test_remote_timeout_and_explicit_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("CINEGIT_PROVIDER_URL", "https://gateway.example/generate")
    monkeypatch.setenv("CINEGIT_DEMO_FALLBACK", "false")
    engine = Engine(tmp_path)

    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("provider timed out")

    monkeypatch.setattr(engine, "remote_generate", timeout)
    workflow = demo_workflow()
    workflow["nodes"][0]["params"]["duration"] = .5
    node = engine.plan(workflow)[0]
    with pytest.raises(RuntimeError, match="模型调用失败"):
        engine.render_node(node, {})
    assert engine.manifest(node["node_hash"]) is None
    with pytest.raises(RuntimeError, match="关键帧模型调用失败"):
        engine.preview(node)
    monkeypatch.setenv("CINEGIT_DEMO_FALLBACK", "true")
    preview = engine.preview(node)
    assert preview["fallback"] is True
    rendered = engine.render_node(node, {})
    assert rendered["fallback"] is True
    assert (tmp_path / rendered["artifact"].removeprefix("/media/")).exists()
    assert engine.plan(workflow)[0]["cache_hit"] is False
