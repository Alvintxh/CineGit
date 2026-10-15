import { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Clapperboard, Pause, Play } from 'lucide-react'
import type { Shot } from './types'

type Clip = { shot: Shot; video?: string; image?: string }

export default function MixedPlayer({clips, selectedId, select}: {clips: Clip[]; selectedId?: string; select: (id: string) => void}) {
  const [playing, setPlaying] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const player = useRef<HTMLVideoElement>(null)
  const index = Math.max(0, clips.findIndex(clip => clip.shot.node_id === selectedId))
  const clip = clips[index]
  const nextId = clips[(index + 1) % clips.length]?.shot.node_id
  const previousId = clips[(index - 1 + clips.length) % clips.length]?.shot.node_id
  useEffect(() => { setElapsed(0) }, [clip?.shot.node_id, clip?.image, clip?.video])
  useEffect(() => {
    const video = player.current
    if (!video) return
    if (playing) void video.play().catch(() => setPlaying(false))
    else video.pause()
  }, [playing, clip?.shot.node_id, clip?.video])
  useEffect(() => {
    if (!playing || !clip || clip.video) return
    const interval = setInterval(() => setElapsed(previous => previous + .1), 100)
    return () => clearInterval(interval)
  }, [playing, clip?.shot.node_id, clip?.video])
  useEffect(() => {
    if (clip && !clip.video && elapsed >= clip.shot.params.duration && playing) {
      if (clips.length > 1 && nextId) select(nextId)
      else setElapsed(0)
    }
  }, [elapsed, playing, clip, nextId, clips.length, select])
  if (!clip) return <div className="stage-empty"><Clapperboard size={30}/><p>选择视频分镜，开始预览</p></div>
  return <div className={`mixed-player motion-${clip.shot.params.camera_motion}`}>
    {clip.video ? <video key={clip.video} ref={player} src={clip.video} playsInline onTimeUpdate={event => setElapsed(event.currentTarget.currentTime)} onEnded={() => { if (clips.length > 1 && nextId) select(nextId); else { if (player.current) player.current.currentTime = 0; setPlaying(false) } }} /> : clip.image ? <img key={clip.image + clip.shot.node_id} className="animatic-image" src={clip.image} alt={`${clip.shot.title}关键帧`} style={{animationDuration: `${clip.shot.params.duration}s`, animationPlayState: playing ? 'running' : 'paused'}} /> : <div className="stage-empty"><Clapperboard size={32}/><strong>{clip.shot.title}</strong><p>请先为这个镜头生成关键帧</p></div>}
    <div className="mixed-label"><span>{clip.video ? 'CACHED VIDEO' : 'KEYFRAME ANIMATIC'}</span><span>{index + 1} / {clips.length}</span></div>
    <div className="mixed-controls"><button className="icon-button" aria-label="上一分镜" onClick={() => previousId && select(previousId)}><ChevronLeft size={17}/></button><button className="mixed-play" aria-label={playing ? '暂停分镜播放' : '播放混合分镜'} onClick={() => setPlaying(!playing)}>{playing ? <Pause size={17}/> : <Play size={17}/>}</button><button className="icon-button" aria-label="下一分镜" onClick={() => nextId && select(nextId)}><ChevronRight size={17}/></button><span>{clip.shot.title}</span><div className="mixed-progress"><span style={{width: `${Math.min(100, elapsed / clip.shot.params.duration * 100)}%`}}/></div><code>{elapsed.toFixed(1)} / {clip.shot.params.duration}s</code></div>
  </div>
}
