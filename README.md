# CineGit

**每一帧，都有来路。** 基于 MCP 的创作工作流录制与视频版本控制工作台。

根据本目录 `黑客松项目.docx` 实现的本地黑客松版本：React + React Flow 创作界面，Python MCP / FastAPI 网关，SHA-256 Merkle DAG 缓存，真实 FFmpeg 增量视频合成，SQLite 持久化。

## 启动

需要 Python 3.11+、[uv](https://docs.astral.sh/uv/getting-started/installation/)、Node.js 20.19+ 和提供 `libx264` / AAC / PNG 编码器的 FFmpeg。

```bash
# macOS 安装运行依赖（已安装可跳过）
brew install uv node ffmpeg

# 在项目根目录运行
./scripts/start.sh
```

打开 **http://127.0.0.1:8000**。API 文档：http://127.0.0.1:8000/docs 。首次启动会生成 3 个分支的真实 720p 演示视频与 2 个市场模板，无需 API Key。服务仅绑定本机。

后续快速启动（前端已构建）：

```bash
uv run uvicorn cinegit.api:app --host 127.0.0.1 --port 8000
```

开发时分别运行：

```bash
uv sync --dev
uv run uvicorn cinegit.api:app --reload --host 127.0.0.1 --port 8000
```

```bash
npm --prefix frontend ci
npm --prefix frontend run dev
```

开发界面 http://127.0.0.1:5173，通过 Vite 代理访问后端。数据默认保存在 `.data/`；设置 `CINEGIT_DATA_DIR` 可隔离多个工作空间。`CINEGIT_PORT=8080 ./scripts/start.sh` 可更换 Web 端口。

## 局域网分享

开放给同一局域网中的设备访问：

```bash
CINEGIT_HOST=0.0.0.0 ./scripts/start.sh
```

前端已构建时可快速启动：

```bash
uv run uvicorn cinegit.api:app --host 0.0.0.0 --port 8000
```

其他设备打开 `http://你的局域网IP:8000`。macOS 可用 `ipconfig getifaddr en0` 查询 Wi-Fi 地址；更换网络后地址可能变化。保持本机服务运行，若 macOS 弹出防火墙连接提示，请允许该服务的传入连接。

此链接进入同一个共享工作区，访问者可以编辑内容，修改会保存到本机。当前版本没有独立账号或只读访问模式。

示例文件：[workflow.json](workflow.json)，可直接从侧栏导入。

## 3 分钟体验

1. 打开「雨夜来信」，播放 9 秒成片，选择第二个镜头。
2. 在提示词末尾添加「日落暖色调」，保持 Seed；点「关键帧预览」。系统先保存草稿，重新计算缓存计划，显示新的关键帧与 CSS 运镜。
3. 切到「关键帧」并播放：时间轴自动混播已有缓存视频与尚未渲染的静态关键帧；用左右箭头切换分镜。
4. 点 **Commit & Render**，填写提交说明。只有变化的分镜调用生成器；其他镜头复用 CAS 中的 MP4。底部显示任务进度，完成通知显示实际命中数与拼接耗时。
5. 在「版本与分支」查看提交树；选择两个提交，用左侧视频同步控制两栏。下方查看实际参数与有效提示词差异。
6. 选 AFTER 版本中修改的镜头，点「合入镜头」，再 Commit；也可回滚历史快照为新提交。
7. 在「工作流市场」Fork 模板，替换全局变量并重新渲染；导出或导入 `workflow.json` 可跨本地工作区复现。

缓存卡片显示**已保存草稿**的缓存计划。编辑后需保存或预览以更新；未保存提示会出现在顶栏。每条分支保留独立草稿，分支创建基于提交快照。

## 已实现

| 文档能力 | 实现 |
| --- | --- |
| MCP 创作录制 | `cinegit_generate` 网关包装生成调用，自动记录 Prompt、Seed、参数、上游节点、输入/输出资产与哈希；真实 stdio 和 Streamable HTTP 协议 |
| 工作流参数化 | 全局 `{{variable}}`、重复短语建议、确认后批量精确替换；变量变化只影响引用节点与下游 |
| DAG 编排 | 校验重复 ID、缺失依赖、环、未定义变量；拓扑生成，按分镜列表顺序拼接 |
| 一级反馈 | 锁定 Seed 的关键帧；CSS 运镜；支持视频与静态分镜的混合播放器 |
| 二级反馈 | SHA-256 内容寻址；跨线程/进程文件锁；仅生成 Cache Miss；异步任务与真实统计 |
| 入库标准化 | 1280×720 / 24fps / yuv420p / H.264 Main / tbn 12288 / AAC 48kHz 双声道，缺音轨自动补齐 |
| 增量成片 | FFmpeg Concat Demuxer `-c copy`，零视频重编码；提供实际毫秒耗时 |
| 视频 Git | 不可变 Commit、父提交、分支、独立草稿、回滚为新提交、含依赖闭包的 Cherry-pick |
| Visual Diff | 双栏视频同步播放/暂停/定位，显示 Prompt、参数、有效变量与依赖导致的变化 |
| 工作流市场 | 发布绑定不可变提交；搜索、预览、免费 Fork、演示购买与 15% 费率记录、来源和许可证保留 |
| 数据可靠性 | SQLite WAL、事务、草稿修订号冲突检测、提交分支前移冲突处理、崩溃任务恢复提示 |
| API 与可移植性 | OpenAPI、版本化 JSON 导入导出、可配置 HTTP 模型适配器 |

## MCP 接入

Claude Desktop 等支持 MCP 的客户端可使用以下配置，将项目路径改为实际绝对路径（`uv` 若不在客户端 PATH 中，请改为 `command -v uv` 的输出）：

```json
{
  "mcpServers": {
    "cinegit": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/CineGit", "run", "python3", "-m", "cinegit.mcp_server"]
    }
  }
}
```

可用工具：`cinegit_list_repositories`、`cinegit_create_repository`、`cinegit_get_workflow`、`cinegit_generate`、`cinegit_parameterize`、`cinegit_commit`、`cinegit_job`、`cinegit_branch`、`cinegit_checkout`、`cinegit_diff`、`cinegit_revert`、`cinegit_cherry_pick`、`cinegit_marketplace`、`cinegit_fork`。

工作流资源：`cinegit://repositories/{repo_id}/workflow`。

示例给 Agent 的指令：

> 创建「城市来信」仓库。使用 cinegit_generate 生成 image_01 图片，seed=42。再生成 video_01，depends_on=["image_01"]，duration=3，camera_motion="zoom_in"。最后提交并查询任务进度。

生成工具支持 `mcp_script`、`mcp_image_gen`、`mcp_video_gen`、`mcp_tts`。本地脚本工具输出文本，本地声音工具生成低音量示例音，不做语音合成。接入真实网关后可使用 LLM / TTS。

独立启动 Streamable HTTP：

```bash
CINEGIT_MCP_TRANSPORT=streamable-http uv run python3 -m cinegit.mcp_server
```

连接 http://127.0.0.1:8001/mcp 。录制只覆盖通过 CineGit 网关的调用；MCP 协议本身不会让一个服务自动截获其他服务的调用。[SDK 传输与集成说明](https://py.sdk.modelcontextprotocol.io/v1/server/)。

## 接入真实模型

复制配置：

```bash
cp .env.example .env
```

配置 `CINEGIT_PROVIDER_URL`、`CINEGIT_PROVIDER_TOKEN` 和 `CINEGIT_PROVIDER_MODEL`，重启后端。接口协议与示例见 [docs/provider.md](docs/provider.md)。密钥只在后端读取，不写入工作流、哈希或前端。

适配器面向自建模型网关，**不是**直接兼容任意厂商的 URL。Flux / Kling / Luma 等需要在网关中转换各自的任务提交、轮询与资产下载协议。超时默认报错；显式开启 `CINEGIT_DEMO_FALLBACK=true` 才回退演示生成，提交统计中会标记 fallback 数量。

## 测试

```bash
uv sync --dev
uv run pytest -q
npm --prefix frontend ci
npm --prefix frontend run build
npm --prefix frontend test
```

后端测试包含真实 MP4 编码、流参数验证、解码完整性、拼接时长、变量与下游失效传播、缓存重用、回滚与 Fork、HTTP 接口，以及真实 MCP stdio / Streamable HTTP 客户端调用。前端测试覆盖草稿保存、新建仓库和分支切换。

## 目录

```text
cinegit/          数据模型、SQLite、Merkle DAG、FFmpeg、API、MCP 服务
frontend/         React / TypeScript / React Flow 工作台
scripts/          启动与演示数据工具
tests/            后端和 MCP 集成测试
docs/             模型网关协议、架构、需求范围、路演讲稿
.data/            本机数据库、CAS、导出成片（不进版本库）
```

## 版本边界

这是单机、单用户的完整演示闭环。默认画面来自可确定复现的程序化城市绘制与 FFmpeg 运镜，不冒充真实 AI 视频。变量建议采用离线重复短语检测，没有声称调用 LLM。成本节省为按 `CINEGIT_ESTIMATED_SHOT_COST` 计算的估算，演示生成器没有真实云端开销。

原文中的 0.8 秒、30 秒与 0.15 秒是目标，受模型、硬件、片长与编码器影响，界面展示实际时间，不保证固定延迟。市场使用本地 SQLite，不提供真实支付、云托管、账号或许可证执法；公开部署需另行建设身份认证、任务队列和支付系统。已完成节点保留缓存，进程中断的未完成任务会标记失败，需重新提交。
