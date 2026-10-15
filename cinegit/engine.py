import base64
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter
from filelock import FileLock

from .models import Workflow

PROFILE = {"engine": "cinegit-1", "width": 1280, "height": 720, "fps": 24, "timebase": 12288, "audio": "aac-stereo-48000"}


def digest(value):
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    result = hashlib.sha256(payload.encode()).hexdigest()
    return result


def resolve_prompt(template, variables):
    result = re.sub(r"{{\s*([A-Za-z][A-Za-z0-9_]*)\s*}}", lambda match: variables[match.group(1)], template)
    return result


def plan_workflow(workflow, provider="demo"):
    workflow = Workflow.model_validate(workflow).model_dump()
    pending = list(workflow["nodes"])
    hashes = {}
    planned = []
    while pending:
        ready = [node for node in pending if all(dep in hashes for dep in node["depends_on"])]
        for node in ready:
            prompt = resolve_prompt(node["prompt_template"], workflow["variables"])
            value = {"tool": node["mcp_tool"], "prompt": prompt, "params": node["params"], "inputs": [hashes[dep] for dep in node["depends_on"]], "provider": provider, "profile": PROFILE}
            node_hash = digest(value)
            hashes[node["node_id"]] = node_hash
            planned.append({**node, "resolved_prompt": prompt, "node_hash": node_hash})
            pending.remove(node)
    return planned


def run_ffmpeg(arguments, timeout=180):
    result = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *arguments], capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"FFmpeg 失败：{result.stderr[-1500:]}")


def draw_keyframe(node, target):
    seed = int(node["node_hash"][:12], 16)
    rng = random.Random(seed)
    width, height = 1280, 720
    is_warm = any(word in node["resolved_prompt"].lower() for word in ["日落", "沙漠", "暖", "sunset", "desert", "水墨"])
    base = (38, 25, 37) if is_warm else (7, 21, 35)
    glow = (239, 135, 81) if is_warm else (53, 183, 169)
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        intensity = 0.3 + 0.7 * math.exp(-((y - 390) / 220) ** 2)
        draw.line((0, y, width, y), fill=tuple(int(base[i] + glow[i] * intensity * 0.28) for i in range(3)))
    haze = Image.new("RGB", (width, height))
    haze_draw = ImageDraw.Draw(haze)
    haze_draw.ellipse((590, 90, 920, 420), fill=tuple(int(c * 0.7) for c in glow))
    image = Image.blend(image, haze.filter(ImageFilter.GaussianBlur(95)), 0.28)
    draw = ImageDraw.Draw(image)
    draw.ellipse((900, 95, 1015, 210), fill=(179, 194, 179) if not is_warm else (246, 180, 107))
    for layer in range(3):
        x = -10
        floor = 520 + layer * 46
        while x < width:
            building_width = rng.randint(35, 105)
            top = floor - rng.randint(70, 290 + layer * 35)
            color = tuple(int(c * (0.8 - layer * 0.2)) for c in (24, 45, 53))
            draw.rectangle((x, top, x + building_width, floor), fill=color)
            if rng.random() > 0.45:
                draw.line((x + 5, top, x + building_width - 5, top), fill=glow, width=2)
            for wx in range(x + 8, x + building_width - 4, 13):
                for wy in range(top + 12, floor - 5, 19):
                    if rng.random() > 0.5:
                        draw.rectangle((wx, wy, wx + 3, wy + 6), fill=glow if rng.random() > 0.15 else (210, 93, 133))
            x += building_width + rng.randint(6, 22)
    draw.polygon([(0, 720), (550, 510), (730, 510), (1280, 720)], fill=(9, 22, 28))
    for y in range(535, 720, 10):
        spread = (y - 510) * 1.8
        draw.line((640 - spread, y, 640 + spread, y), fill=tuple(int(c * rng.uniform(0.15, 0.4)) for c in glow), width=2)
    person_x = 550 + rng.randint(-70, 130)
    draw.ellipse((person_x - 11, 455, person_x + 11, 477), fill=(10, 14, 20))
    draw.polygon([(person_x - 13, 478), (person_x + 12, 478), (person_x + 24, 555), (person_x - 24, 555)], fill=(14, 20, 27))
    draw.line((person_x - 10, 550, person_x - 13, 585), fill=(7, 13, 18), width=7)
    draw.line((person_x + 10, 550, person_x + 13, 585), fill=(7, 13, 18), width=7)
    draw.arc((person_x - 45, 435, person_x + 45, 495), 180, 360, fill=glow, width=3)
    if not is_warm:
        for index in range(190):
            x, y = rng.randrange(width), rng.randrange(height)
            draw.line((x, y, x - 5, y + rng.randint(7, 22)), fill=(57, 87, 99), width=1)
    draw.rectangle((0, 0, width, 40), fill=(5, 10, 15))
    draw.rectangle((0, height - 40, width, height), fill=(5, 10, 15))
    image.save(target)


class Engine:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.cache = self.root / "cache"
        self.outputs = self.root / "outputs"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.outputs.mkdir(parents=True, exist_ok=True)
        self.endpoint = os.getenv("CINEGIT_PROVIDER_URL", "")
        self.provider = "http:" + digest({"endpoint": self.endpoint, "model": os.getenv("CINEGIT_PROVIDER_MODEL", "default")}) if self.endpoint else "demo"

    def plan(self, workflow):
        result = plan_workflow(workflow, self.provider)
        for node in result:
            manifest = self.manifest(node["node_hash"])
            node["cache_hit"] = manifest is not None
            if manifest:
                node.update({key: manifest.get(key) for key in ["artifact", "preview_img", "artifact_mp4", "fallback"]})
        return result

    def manifest(self, node_hash):
        path = self.cache / f"{node_hash}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        if self.endpoint and data.get("fallback"):
            return None
        if not (self.root / data["artifact"].removeprefix("/media/")).exists():
            return None
        return data

    def preview(self, node):
        target = self.cache / f"{node['node_hash']}_keyframe.webp"
        metadata = self.cache / f"{node['node_hash']}_preview.json"
        fallback = False
        if target.exists():
            if metadata.exists():
                fallback = json.loads(metadata.read_text()).get("fallback", False)
            else:
                manifest = self.cache / f"{node['node_hash']}.json"
                fallback = json.loads(manifest.read_text()).get("fallback", False) if manifest.exists() else False
        if not target.exists() or (self.endpoint and fallback):
            with tempfile.NamedTemporaryFile(suffix=".webp", dir=self.cache, delete=False) as temporary:
                temporary_path = Path(temporary.name)
            try:
                if self.endpoint:
                    try:
                        self.remote_generate(node, temporary_path, [], preview=True)
                        with Image.open(temporary_path) as image:
                            image.convert("RGB").resize((1280, 720)).save(temporary_path, format="WEBP")
                    except (httpx.HTTPError, ValueError, OSError) as error:
                        if os.getenv("CINEGIT_DEMO_FALLBACK", "false").lower() != "true":
                            raise RuntimeError(f"关键帧模型调用失败：{error}") from error
                        fallback = True
                        draw_keyframe(node, temporary_path)
                else:
                    draw_keyframe(node, temporary_path)
                temporary_path.replace(target)
                metadata.write_text(json.dumps({"fallback": fallback}))
            finally:
                temporary_path.unlink(missing_ok=True)
        return {"preview_img": f"/media/cache/{target.name}", "fallback": fallback}

    def remote_generate(self, node, target, inputs, preview=False):
        token = os.getenv("CINEGIT_PROVIDER_TOKEN", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        payload = {"tool": "mcp_image_gen" if preview else node["mcp_tool"], "prompt": node["resolved_prompt"], "params": node["params"], "model": os.getenv("CINEGIT_PROVIDER_MODEL", "default"), "preview": preview, "inputs": inputs}
        timeout = float(os.getenv("CINEGIT_PROVIDER_TIMEOUT", "120"))
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.post(self.endpoint, json=payload, headers=headers)
            response.raise_for_status()
            if response.headers.get("content-type", "").startswith("application/json"):
                data = response.json()
                if "base64" in data:
                    target.write_bytes(base64.b64decode(data["base64"], validate=True))
                elif "url" in data:
                    asset = client.get(data["url"])
                    asset.raise_for_status()
                    target.write_bytes(asset.content)
                else:
                    raise ValueError("模型网关须返回媒体内容、base64 或 url")
            else:
                target.write_bytes(response.content)
        if not target.stat().st_size:
            raise ValueError("模型网关返回空文件")

    def normalize(self, source, target, duration):
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(source)], capture_output=True, text=True, check=True)
        streams = json.loads(probe.stdout)["streams"]
        has_audio = any(stream["codec_type"] == "audio" for stream in streams)
        arguments = ["-i", str(source)]
        if not has_audio:
            arguments.extend(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"])
        arguments.extend(["-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=24,format=yuv420p,tpad=stop_mode=clone:stop_duration=20", "-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0", "-af", "apad", "-t", str(duration), "-c:v", "libx264", "-profile:v", "main", "-preset", "ultrafast", "-crf", "21", "-video_track_timescale", "12288", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k", "-movflags", "+faststart", str(target)])
        run_ffmpeg(arguments)

    def render_node(self, node, artifacts):
        node_hash = node["node_hash"]
        with FileLock(str(self.cache / f"{node_hash}.lock"), timeout=240):
            existing = self.manifest(node_hash)
            if existing:
                return {**node, **existing, "cache_hit": True, "elapsed_ms": 0}
            started = time.perf_counter()
            tool = node["mcp_tool"]
            extension = {"mcp_video_gen": "mp4", "mcp_image_gen": "webp", "mcp_tts": "wav", "mcp_script": "txt"}[tool]
            target = self.cache / f"{node_hash}.{extension}"
            fallback = False
            with tempfile.TemporaryDirectory(dir=self.cache) as directory:
                work = Path(directory)
                raw = work / f"source.{extension}"
                if self.endpoint:
                    inputs = []
                    for dep in node["depends_on"]:
                        artifact = artifacts[dep]
                        path = self.root / artifact["artifact"].removeprefix("/media/")
                        inputs.append({"node_id": dep, "tool": artifact["mcp_tool"], "base64": base64.b64encode(path.read_bytes()).decode()})
                    try:
                        self.remote_generate(node, raw, inputs)
                    except (httpx.HTTPError, ValueError) as error:
                        if os.getenv("CINEGIT_DEMO_FALLBACK", "false").lower() != "true":
                            raise RuntimeError(f"模型调用失败：{error}") from error
                        fallback = True
                if not self.endpoint or fallback:
                    if tool == "mcp_script":
                        raw.write_text(node["resolved_prompt"], encoding="utf-8")
                    elif tool == "mcp_tts":
                        run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000", "-t", str(node["params"].get("duration", 3)), "-af", "volume=0.03", str(raw)])
                    else:
                        image_source = next((artifacts[dep]["artifact"] for dep in node["depends_on"] if artifacts[dep]["mcp_tool"] == "mcp_image_gen"), None)
                        image_path = work / "keyframe.webp"
                        if image_source:
                            shutil.copyfile(self.root / image_source.removeprefix("/media/"), image_path)
                        else:
                            draw_keyframe(node, image_path)
                        if tool == "mcp_image_gen":
                            shutil.copyfile(image_path, raw)
                        else:
                            frames = round(node["params"].get("duration", 3) * 24)
                            motion = node["params"].get("camera_motion", "zoom_in")
                            zoom = {"zoom_in": "1+0.0008*on", "zoom_out": "1.12-0.0008*on"}.get(motion, "1.12")
                            x = {"pan_right": "on*1.1", "pan_left": "iw-iw/zoom-on*1.1"}.get(motion, "iw/2-iw/zoom/2")
                            filter_value = f"zoompan=z='{zoom}':x='{x}':y='ih/2-ih/zoom/2':d={frames}:s=1280x720:fps=24,format=yuv420p"
                            audio = next((artifacts[dep]["artifact"] for dep in node["depends_on"] if artifacts[dep]["mcp_tool"] == "mcp_tts"), None)
                            audio_input = ["-i", str(self.root / audio.removeprefix("/media/"))] if audio else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
                            run_ffmpeg(["-i", str(image_path), *audio_input, "-vf", filter_value, "-t", str(frames / 24), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(raw)])
                if tool == "mcp_video_gen":
                    self.normalize(raw, work / "normalized.mp4", node["params"].get("duration", 3))
                    shutil.copyfile(work / "normalized.mp4", target)
                    keyframe = self.cache / f"{node_hash}_keyframe.webp"
                    run_ffmpeg(["-i", str(target), "-frames:v", "1", str(work / "frame.png")])
                    with Image.open(work / "frame.png") as image:
                        image.save(keyframe, format="WEBP")
                    (self.cache / f"{node_hash}_preview.json").unlink(missing_ok=True)
                elif tool == "mcp_image_gen":
                    with Image.open(raw) as image:
                        image.convert("RGB").resize((1280, 720)).save(target, format="WEBP")
                else:
                    shutil.copyfile(raw, target)
            artifact_url = f"/media/cache/{target.name}"
            manifest = {"artifact": artifact_url, "artifact_mp4": artifact_url if tool == "mcp_video_gen" else None, "preview_img": f"/media/cache/{node_hash}_keyframe.webp" if tool == "mcp_video_gen" else artifact_url if tool == "mcp_image_gen" else None, "fallback": fallback, "mcp_tool": tool, "node_hash": node_hash}
            manifest_path = self.cache / f"{node_hash}.json"
            temporary_manifest = manifest_path.with_suffix(".json.tmp")
            temporary_manifest.write_text(json.dumps(manifest))
            temporary_manifest.replace(manifest_path)
            return {**node, **manifest, "cache_hit": False, "elapsed_ms": round((time.perf_counter() - started) * 1000)}

    def concatenate(self, nodes, output_id):
        started = time.perf_counter()
        video_nodes = [node for node in nodes if node["mcp_tool"] == "mcp_video_gen"]
        target = self.outputs / f"{output_id}.mp4"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", dir=self.outputs, delete=False) as file:
            concat_path = Path(file.name)
            for node in video_nodes:
                path = self.root / node["artifact"].removeprefix("/media/")
                escaped_path = str(path).replace("'", "'\\''")
                file.write(f"file '{escaped_path}'\n")
        try:
            run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat_path), "-c", "copy", "-movflags", "+faststart", str(target)])
        finally:
            concat_path.unlink(missing_ok=True)
        return {"video_url": f"/media/outputs/{target.name}", "concat_ms": round((time.perf_counter() - started) * 1000), "duration": sum(node["params"].get("duration", 3) for node in video_nodes)}
