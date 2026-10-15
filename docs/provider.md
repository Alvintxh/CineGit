# HTTP 模型网关协议

设置 `CINEGIT_PROVIDER_URL=https://your-trusted-gateway.example/generate` 后，所有工具通过该可信网关生成。适配器同步等待媒体结果；如果模型服务采用异步任务，网关负责提交任务、轮询并在超时前返回媒体。

## 请求

```http
POST /generate
Content-Type: application/json
Authorization: Bearer <CINEGIT_PROVIDER_TOKEN>
```

```json
{
  "tool": "mcp_video_gen",
  "prompt": "已经替换变量的实际提示词",
  "params": {"seed": 42, "duration": 3, "camera_motion": "zoom_in"},
  "model": "your-model-version",
  "preview": false,
  "inputs": [
    {"node_id": "image_01", "tool": "mcp_image_gen", "base64": "..."}
  ]
}
```

`tool` 取 `mcp_script`、`mcp_image_gen`、`mcp_video_gen`、`mcp_tts`。关键帧请求使用 `mcp_image_gen` 且 `preview=true`，保持视频节点的种子与提示词。上游输入按 `depends_on` 顺序发送，使用 Base64 包含真实资产；网关应按工具类型解析。

## 响应

以下三种形式任选其一：

1. 直接返回媒体二进制，Content-Type 为 `video/mp4`、`image/png`、`image/webp`、`audio/wav` 或 `text/plain`。
2. JSON：`{"base64":"<encoded media>"}`。
3. JSON：`{"url":"https://trusted-cdn.example/output.mp4"}`，后端下载后入库。

视频入库会强制统一成 1280×720 / 24fps / yuv420p / H.264 / 48kHz 双声道 AAC，补足音轨与不足的尾帧，并截取到指定时长。图像通过 Pillow 转为固定大小的 WebP。媒体 URL 和网关都应由用户可信的服务控制；当前适配器会跟随下载重定向。

## 缓存、故障与配置

1. 缓存键包含实际提示词、工具、参数、上游哈希、输出规范、网关 URL 指纹和模型版本。模型升级后请更新 `CINEGIT_PROVIDER_MODEL`，避免复用旧模型缓存。
2. Bearer Token 不进入缓存键和记录，令牌轮换不会导致全量失效。
3. `CINEGIT_PROVIDER_TIMEOUT` 控制 HTTP 请求超时，默认 120 秒。
4. 默认失败会使任务明确失败，并保留已经完成的节点。设置 `CINEGIT_DEMO_FALLBACK=true` 才允许使用程序化演示输出，manifest 和统计会标记 `fallback=true`。
5. 默认模式不发起外部模型请求。请勿把 DOCX 中的性能估计作为模型 SLA。
