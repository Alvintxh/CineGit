import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_real_stdio_record_generate_commit(tmp_path):
    root = Path(__file__).resolve().parent.parent
    params = StdioServerParameters(command=sys.executable, args=["-m", "cinegit.mcp_server"], cwd=str(root), env={**os.environ, "CINEGIT_DATA_DIR": str(tmp_path), "CINEGIT_PROVIDER_URL": "", "CINEGIT_SEED_DEMO": "false"})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            assert "cinegit_generate" in [tool.name for tool in listed.tools]
            created = await session.call_tool("cinegit_create_repository", {"title": "MCP 测试"})
            assert not created.isError
            data = json.loads(created.content[0].text)
            repo_id = data["repo_id"]
            generated = await session.call_tool("cinegit_generate", {"repo_id": repo_id, "node_id": "recorded_shot", "prompt": "暖色日落城市", "seed": 2026, "duration": .5})
            assert not generated.isError, generated
            recorded = json.loads(generated.content[0].text)
            assert recorded["status"] == "success"
            assert recorded["node"]["artifact_mp4"].endswith(".mp4")
            assert recorded["node"]["cache_hit"] is False
            repeated = await session.call_tool("cinegit_generate", {"repo_id": repo_id, "node_id": "recorded_shot", "prompt": "暖色日落城市", "seed": 2026, "duration": .5})
            assert json.loads(repeated.content[0].text)["node"]["cache_hit"] is True
            workflow = await session.read_resource(f"cinegit://repositories/{repo_id}/workflow")
            resource = json.loads(workflow.contents[0].text)
            assert resource["nodes"][-1]["params"]["seed"] == 2026
            invalid = await session.call_tool("cinegit_generate", {"repo_id": repo_id, "node_id": "bad", "prompt": "x", "depends_on": ["absent"]})
            assert invalid.isError


async def test_streamable_http_transport(tmp_path):
    import asyncio
    import socket
    import subprocess

    import httpx
    from mcp.client.streamable_http import streamable_http_client

    root = Path(__file__).resolve().parent.parent
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    env = {**os.environ, "CINEGIT_DATA_DIR": str(tmp_path), "CINEGIT_PROVIDER_URL": "", "CINEGIT_MCP_TRANSPORT": "streamable-http", "CINEGIT_MCP_PORT": str(port)}
    process = subprocess.Popen([sys.executable, "-m", "cinegit.mcp_server"], cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        async with httpx.AsyncClient() as client:
            for attempt in range(100):
                try:
                    response = await client.get(url)
                    if response.status_code < 500:
                        break
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(.03)
        async with streamable_http_client(url) as (read, write, session_id):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name == "CineGit"
                tools = await session.list_tools()
                assert "cinegit_generate" in [tool.name for tool in tools.tools]
                result = await session.call_tool("cinegit_list_repositories", {})
                assert json.loads(result.content[0].text)["status"] == "success"
    finally:
        process.terminate()
        process.wait(timeout=10)
