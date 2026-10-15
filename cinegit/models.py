import re

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Node(BaseModel):
    model_config = ConfigDict(extra="ignore")
    node_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    title: str = Field(default="新分镜", max_length=120)
    mcp_tool: str = "mcp_video_gen"
    prompt_template: str = Field(min_length=1, max_length=10000)
    params: dict = Field(default_factory=lambda: {"seed": 42, "duration": 3, "camera_motion": "zoom_in"})
    depends_on: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_params(self):
        if self.mcp_tool not in {"mcp_video_gen", "mcp_image_gen", "mcp_script", "mcp_tts"}:
            raise ValueError("不支持的 MCP 工具")
        self.params = {"seed": 42, "duration": 3, "camera_motion": "zoom_in", **self.params}
        duration = self.params["duration"]
        if isinstance(duration, bool) or not isinstance(duration, (float, int)) or not 0.5 <= duration <= 20:
            raise ValueError("duration 必须为 0.5–20 秒")
        seed = self.params.get("seed", 42)
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2147483647:
            raise ValueError("seed 必须为 0–2147483647 的整数")
        if self.params.get("camera_motion", "zoom_in") not in {"zoom_in", "zoom_out", "pan_left", "pan_right", "static"}:
            raise ValueError("未知运镜方式")
        return self


class Workflow(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = Field(default="未命名影片", min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    author: str = Field(default="@local_creator", max_length=80)
    license: str = Field(default="CC-BY-4.0", max_length=80)
    variables: dict[str, str] = Field(default_factory=dict, max_length=30)
    nodes: list[Node] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def validate_graph(self):
        ids = [node.node_id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("节点 ID 不能重复")
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name) for name in self.variables):
            raise ValueError("变量名须以字母开头，只含字母、数字和下划线")
        complete = set()
        pending = list(self.nodes)
        while pending:
            ready = [node for node in pending if set(node.depends_on) <= complete]
            if not ready:
                raise ValueError("依赖图包含循环或不存在的节点")
            for node in ready:
                missing = set(re.findall(r"{{\s*([A-Za-z][A-Za-z0-9_]*)\s*}}", node.prompt_template)) - self.variables.keys()
                if missing:
                    raise ValueError(f"未定义的变量：{', '.join(sorted(missing))}")
                complete.add(node.node_id)
                pending.remove(node)
        if not any(node.mcp_tool == "mcp_video_gen" for node in self.nodes):
            raise ValueError("工作流至少需要一个视频节点")
        return self


class SaveDraft(BaseModel):
    workflow: Workflow
    revision: int


class CommitRequest(BaseModel):
    message: str = Field(min_length=1, max_length=300)
    revision: int


class BranchRequest(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_/-]{0,59}$")
    from_commit: str | None = None


class RecordRequest(BaseModel):
    node: Node
    revision: int


class DistillRequest(BaseModel):
    variables: dict[str, str] = Field(min_length=1, max_length=30)
    revision: int


class PublishRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    price: float = Field(default=0, ge=0, le=9999)
    tags: list[str] = Field(default_factory=list, max_length=6)


class CherryPickRequest(BaseModel):
    commit: str
    node_ids: list[str] = Field(min_length=1)
    revision: int
