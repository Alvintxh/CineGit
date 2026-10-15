import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Background, Controls, Handle, Position, ReactFlow } from '@xyflow/react'
import { ArrowRight, ArrowUpRight, Check, ChevronDown, CircleDot, Clapperboard, Code2, Copy, Download, FileCode2, Film, FolderGit2, GitBranch, GitCommitHorizontal, GitCompareArrows, GitFork, Layers3, LoaderCircle, Maximize2, Network, Play, Plus, Radio, RefreshCw, RotateCcw, Save, Search, Settings2, ShieldCheck, Sparkles, Store, Terminal, Trash2, Upload, WandSparkles, X, Zap } from 'lucide-react'
import type { Commit, Diff, Job, Listing, Planned, Repo, RepoSummary, Shot, Workflow } from './types'
import { api } from './api'
import MixedPlayer from './MixedPlayer'

const motions: Record<string, string> = { zoom_in: '推进 ↗', zoom_out: '拉远 ↙', pan_left: '左移 ←', pan_right: '右移 →', static: '固定 ·' }
const tools: Record<string, string> = { mcp_video_gen: '视频生成', mcp_image_gen: '关键帧生成', mcp_script: '脚本', mcp_tts: '声音' }
const clone = <T,>(value: T): T => structuredClone(value)
const time = (seconds: number) => `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`
const fmt = (value: unknown) => typeof value === 'string' ? value : JSON.stringify(value, null, 2)

function ShotNode({ data, selected }: { data: Record<string, unknown>; selected: boolean }) {
  const shot = data.shot as Planned
  return <div className={`flow-shot ${selected ? 'selected' : ''}`}><Handle type="target" position={Position.Left} /><div className="flow-shot-top"><span>{String(data.index).padStart(2, '0')}</span><span>{tools[shot.mcp_tool]}</span>{shot.cache_hit ? <Zap size={13} className="green" /> : <CircleDot size={13} className="orange" />}</div>{shot.preview_img && <img src={shot.preview_img} alt="" />}<strong>{shot.title}</strong><div className="flow-shot-bottom"><code>{shot.node_hash?.slice(0, 8) || 'DRAFT'}</code><span>{shot.cache_hit ? 'CACHED' : '待渲染'}</span></div><Handle type="source" position={Position.Right} /></div>
}
function CommitNode({ data }: { data: Record<string, unknown> }) {
  const commit = data.commit as Commit
  return <div className={`commit-node ${data.active ? 'active' : ''}`}><Handle type="target" position={Position.Top} /><div><GitCommitHorizontal size={16} /><code>{commit.hash.slice(0, 8)}</code><span>{commit.branch}</span></div><strong>{commit.message}</strong><small>{commit.stats.cache_hits}/{commit.stats.total_nodes} cached · {new Date(commit.created_at).toLocaleTimeString('zh-CN')}</small><Handle type="source" position={Position.Bottom} /></div>
}
const nodeTypes = { shot: ShotNode, commit: CommitNode }

function Modal({ title, subtitle, children, close }: { title: string; subtitle?: string; children: ReactNode; close: () => void }) {
  const panel = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    panel.current?.focus()
    const listener = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
      if (event.key === 'Tab' && panel.current) {
        const elements = [...panel.current.querySelectorAll<HTMLElement>('button,input,select,textarea,a[href]')].filter(item => !item.hasAttribute('disabled'))
        const first = elements[0], last = elements[elements.length - 1]
        if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) { event.preventDefault(); last?.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }
    }
    window.addEventListener('keydown', listener)
    return () => { window.removeEventListener('keydown', listener); previous?.focus() }
  }, [close])
  return <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) close() }}><div className="modal" ref={panel} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}><button className="icon-button modal-close" onClick={close} aria-label="关闭"><X size={19} /></button><div className="eyebrow">CINEGIT / STUDIO</div><h2>{title}</h2>{subtitle && <p className="muted">{subtitle}</p>}{children}</div></div>
}

export default function App() {
  const [repos, setRepos] = useState<RepoSummary[]>([])
  const [initialLoading, setInitialLoading] = useState(true)
  const [repo, setRepo] = useState<Repo | null>(null)
  const [draft, setDraft] = useState<Workflow | null>(null)
  const [selectedId, setSelectedId] = useState('shot_02')
  const [tab, setTab] = useState('studio')
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState<{ text: string; error: boolean } | null>(null)
  const [modal, setModal] = useState('')
  const closeModal = useCallback(() => setModal(''), [])
  const [modalText, setModalText] = useState('')
  const [modalExtra, setModalExtra] = useState('')
  const [price, setPrice] = useState(0)
  const [job, setJob] = useState<Job | null>(null)
  const [preview, setPreview] = useState<{ node_id: string; src: string } | null>(null)
  const [mode, setMode] = useState<'film' | 'preview'>('film')
  const [market, setMarket] = useState<Listing[]>([])
  const [query, setQuery] = useState('')
  const [paidListing, setPaidListing] = useState<Listing | null>(null)
  const [selectedCommit, setSelectedCommit] = useState('')
  const [diffLeft, setDiffLeft] = useState('')
  const [diffRight, setDiffRight] = useState('working')
  const [diff, setDiff] = useState<Diff | null>(null)
  const [pick, setPick] = useState<string[]>([])
  const [health, setHealth] = useState({ provider: 'demo', ffmpeg: true })
  const [playhead, setPlayhead] = useState(0)
  const [newTool, setNewTool] = useState('mcp_video_gen')
  const [newDependencies, setNewDependencies] = useState<string[]>([])
  const [suggestions, setSuggestions] = useState<{ name: string; value: string; occurrences: number }[]>([])
  const video = useRef<HTMLVideoElement>(null)
  const leftVideo = useRef<HTMLVideoElement>(null)
  const rightVideo = useRef<HTMLVideoElement>(null)
  const importInput = useRef<HTMLInputElement>(null)
  const inFlight = job?.state === 'queued' || job?.state === 'running'
  const localDirty = !!draft && !!repo && JSON.stringify(draft) !== JSON.stringify(repo.workflow)
  const dirty = localDirty || repo?.dirty
  const selected = draft?.nodes.find(node => node.node_id === selectedId) || draft?.nodes[0]
  const planned = repo?.plan.find(node => node.node_id === selected?.node_id)
  const selectedIndex = draft?.nodes.findIndex(node => node.node_id === selected?.node_id) || 0
  const totalDuration = draft?.nodes.filter(node => node.mcp_tool === 'mcp_video_gen').reduce((sum, node) => sum + node.params.duration, 0) || 0

  function notify(text: string, error = false) { setNotice({ text, error }) }
  useEffect(() => { if (!notice) return; const timeout = setTimeout(() => setNotice(null), notice.error ? 12000 : 5500); return () => clearTimeout(timeout) }, [notice])
  const refreshRepos = useCallback(async () => { const data = await api<{ repos: RepoSummary[] }>('/repos'); setRepos(data.repos); return data.repos }, [])
  const loadRepo = useCallback(async (id: string) => {
    const data = await api<{ repo: Repo }>(`/repos/${id}`)
    setRepo(data.repo); setDraft(clone(data.repo.workflow)); setPreview(null)
    setSelectedId(previous => data.repo.workflow.nodes.some(node => node.node_id === previous) ? previous : data.repo.workflow.nodes[0].node_id)
    setDiffLeft(data.repo.head || ''); setSelectedCommit(data.repo.head || ''); setDiffRight('working'); setDiff(null); setPick([])
    const active = data.repo.jobs.find(item => ['running', 'queued'].includes(item.state)); setJob(active || null)
    return data.repo
  }, [])
  useEffect(() => { void (async () => { try { const list = await refreshRepos(); const savedId = localStorage.getItem('cinegit.repo'); const target = list.find(item => item.id === savedId) || list[list.length - 1]; if (target) await loadRepo(target.id); const state = await api<{provider: string; ffmpeg: boolean}>('/health'); setHealth(state) } catch (error) { notify(String(error), true) } finally { setInitialLoading(false) } })() }, [loadRepo, refreshRepos])
  useEffect(() => { if (repo) localStorage.setItem('cinegit.repo', repo.id) }, [repo?.id])
  useEffect(() => {
    if (!job || !inFlight) return
    let disposed = false
    const interval = setInterval(() => { void (async () => {
      try { const data = await api<{ job: Job }>(`/jobs/${job.id}`); if (disposed) return; setJob(data.job)
        if (['success', 'conflict', 'error'].includes(data.job.state)) {
          clearInterval(interval)
          if (repo) await loadRepo(repo.id)
          setJob(data.job)
          notify(data.job.state === 'success' ? `Commit 完成 · ${data.job.stats?.cache_hits}/${data.job.stats?.total_nodes} 节点命中缓存 · 拼接 ${data.job.stats?.concat_ms}ms` : data.job.error || '渲染失败', data.job.state !== 'success')
        }
      } catch (error) { if (!disposed) notify(String(error), true) }
    })() }, 1000)
    return () => { disposed = true; clearInterval(interval) }
  }, [job?.id, inFlight, loadRepo, repo?.id])
  useEffect(() => { if (tab === 'market') void api<{listings: Listing[]}>('/market').then(data => setMarket(data.listings)).catch(error => notify(String(error), true)) }, [tab])
  useEffect(() => {
    if (tab !== 'history' || !repo || !diffLeft) return
    let disposed = false
    void api<Diff>(`/repos/${repo.id}/diff?left=${diffLeft}&right=${diffRight}`).then(data => { if (!disposed) { setDiff(data); setPick([]) } }).catch(error => { if (!disposed) notify(String(error), true) })
    return () => { disposed = true }
  }, [tab, repo?.id, repo?.revision, diffLeft, diffRight])

  async function action(label: string, task: () => Promise<void>) {
    if (busy) return
    setBusy(label)
    try { await task() } catch (error) { notify(error instanceof Error ? error.message : String(error), true) } finally { setBusy('') }
  }
  function open(name: string, text = '', extra = '') { setModalText(text); setModalExtra(extra); setModal(name) }
  function acceptRepo(next: Repo) { if (repo?.id !== next.id) { setDiffLeft(next.head || ''); setDiffRight('working'); setSelectedCommit(next.head || ''); setDiff(null); setPick([]); setJob(null) } setRepo(next); setDraft(clone(next.workflow)); setPreview(null); if (!next.workflow.nodes.some(node => node.node_id === selectedId)) setSelectedId(next.workflow.nodes[0].node_id) }
  async function saveDraft() {
    if (!repo || !draft) throw new Error('工作区尚未加载')
    if (!localDirty) return repo
    const data = await api<{repo: Repo}>(`/repos/${repo.id}/draft`, {workflow: draft, revision: repo.revision}, 'PUT')
    acceptRepo(data.repo)
    return data.repo
  }
  function editNode(patch: Partial<Shot>) {
    if (!draft || !selected) return
    setDraft({ ...draft, nodes: draft.nodes.map(node => node.node_id === selected.node_id ? { ...node, ...patch } : node) })
    setPreview(null)
  }
  async function showPreview() {
    const current = await saveDraft()
    if (!selected) return
    const data = await api<{preview_img: string; fallback?: boolean}>(`/repos/${current.id}/preview/${selected.node_id}`, {})
    setPreview({node_id: selected.node_id, src: data.preview_img}); setMode('preview')
    notify(data.fallback ? '模型不可用，关键帧已回退为演示画面' : '关键帧已更新，种子保持锁定', !!data.fallback)
  }
  async function switchRepo(id: string) { if (localDirty) await saveDraft(); await loadRepo(id); setMode('film') }
  async function fork(listing: Listing, paid = false) {
    const data = await api<{repo: Repo}>(`/market/${listing.id}/fork`, {accept_demo_purchase: paid})
    await refreshRepos(); acceptRepo(data.repo); setTab('studio'); setModal(''); notify('已 Fork 到你的工作区，替换变量即可复现')
  }
  async function confirmModal() {
    if (!repo && modal !== 'new') return
    if (modal === 'commit' || modal === 'revert') {
      const current = await saveDraft()
      const endpoint = modal === 'revert' ? `/repos/${current.id}/revert/${selectedCommit}` : `/repos/${current.id}/commits`
      const data = await api<{job: Job}>(endpoint, {message: modalText, revision: current.revision})
      setJob(data.job); setMode('film'); setModal(''); if (['success', 'error', 'conflict'].includes(data.job.state)) { await loadRepo(current.id); setJob(data.job) }
    } else if (modal === 'branch') {
      const current = await saveDraft()
      const data = await api<{repo: Repo}>(`/repos/${current.id}/branches`, {name: modalText, from_commit: modalExtra || null})
      acceptRepo(data.repo); setModal(''); notify(`已切换到 ${modalText}`)
    } else if (modal === 'new') {
      const data = await api<{repo: Repo}>('/repos', null)
      data.repo.workflow.title = modalText || '未命名影片'
      const updated = await api<{repo: Repo}>(`/repos/${data.repo.id}/draft`, {workflow: data.repo.workflow, revision: data.repo.revision}, 'PUT')
      await refreshRepos(); acceptRepo(updated.repo); setSelectedCommit(''); setDiffLeft(''); setModal(''); setTab('studio')
    } else if (modal === 'publish' && repo) {
      await api(`/repos/${repo.id}/publish`, {title: modalText, description: modalExtra, price, tags: ['创作配方', '社区分享']})
      setModal(''); setTab('market'); const data = await api<{listings: Listing[]}>('/market'); setMarket(data.listings); notify('已发布当前提交的快照')
    } else if (modal === 'distill') {
      const current = await saveDraft()
      const data = await api<{repo: Repo}>(`/repos/${current.id}/distill`, {variables: {[modalText]: modalExtra}, revision: current.revision})
      acceptRepo(data.repo); setModal(''); notify('已将原文替换为全局变量槽位')
    } else if (modal === 'variable' && draft) {
      if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(modalText)) throw new Error('变量名须以字母开头，只含字母、数字、下划线')
      if (modalText in draft.variables) throw new Error('变量已存在')
      setDraft({...draft, variables: {...draft.variables, [modalText]: modalExtra}}); setModal('')
    } else if (modal === 'node' && draft) {
      const node: Shot = {node_id: `shot_${Date.now().toString(36)}`, title: modalText || '新分镜', prompt_template: modalExtra, mcp_tool: newTool, params: {seed: 42, duration: 3, camera_motion: 'zoom_in'}, depends_on: newDependencies}
      setDraft({...draft, nodes: [...draft.nodes, node]}); setSelectedId(node.node_id); setModal('')
    } else if (modal === 'purchase' && paidListing) { await fork(paidListing, true) }
  }
  function syncVideos(event: 'play' | 'pause' | 'seek') {
    const left = leftVideo.current, right = rightVideo.current
    if (!left || !right) return
    if (event === 'play') { right.currentTime = left.currentTime; void right.play().catch(() => {}) }
    if (event === 'pause') right.pause()
    if (event === 'seek') right.currentTime = left.currentTime
  }

  const timeline = draft?.nodes.filter(node => node.mcp_tool === 'mcp_video_gen') || []
  const flowNodes = draft?.nodes.map((node, index) => ({id: node.node_id, type: 'shot', position: {x: index * 245, y: node.depends_on.length ? 60 : 15}, selected: node.node_id === selected?.node_id, data: {shot: {...node, ...repo?.plan.find(item => item.node_id === node.node_id), title: node.title}, index: index + 1}})) || []
  const flowEdges = draft?.nodes.flatMap(node => node.depends_on.map(dep => ({id: `${dep}-${node.node_id}`, source: dep, target: node.node_id, animated: true, style: {stroke: '#a7c96a'}}))) || []
  const chronological = [...(repo?.commits || [])].reverse()
  const branchNames = [...new Set(chronological.map(item => item.branch))]
  const commitNodes = chronological.map((commit, index) => ({ id: commit.hash, type: 'commit', position: {x: branchNames.indexOf(commit.branch) * 315, y: index * 130}, data: {commit, active: commit.hash === selectedCommit} }))
  const commitEdges = chronological.filter(commit => commit.parent_commit).map(commit => ({id: commit.hash, source: commit.parent_commit!, target: commit.hash, type: 'smoothstep', style: {stroke: commit.branch === 'main' ? '#b9e680' : '#b79cde', strokeWidth: 2}}))
  const selectedHistory = repo?.commits.find(commit => commit.hash === selectedCommit)
  const latestStats = job?.stats || repo?.commit?.stats

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={event => { event.preventDefault(); setTab('studio') }}><span className="brand-mark"><Clapperboard size={23} /></span>CineGit<span className="beta">BETA</span></a>
      <div className="workspace-label">个人工作空间 <ChevronDown size={13} /></div>
      <nav aria-label="主导航"><button className={tab === 'studio' ? 'nav-link active' : 'nav-link'} onClick={() => setTab('studio')}><Layers3 size={17} />创作工作台<span className="nav-dot" /></button><button className={tab === 'history' ? 'nav-link active' : 'nav-link'} onClick={() => setTab('history')}><GitBranch size={17} />版本与分支<span className="nav-count">{repo?.commits.length || 0}</span></button><button className={tab === 'market' ? 'nav-link active' : 'nav-link'} onClick={() => setTab('market')}><Store size={17} />工作流市场<ArrowUpRight size={14} className="nav-end" /></button></nav>
      <div className="sidebar-divider" /><div className="sidebar-heading">我的影片<button className="icon-button" title="新建影片" onClick={() => open('new', '我的新影片')}><Plus size={15} /></button></div>
      <div className="repo-list">{repos.map(item => <button key={item.id} title={item.title} className={`repo-link ${repo?.id === item.id ? 'current' : ''}`} disabled={inFlight || !!busy} onClick={() => void action('切换影片', () => switchRepo(item.id))}><FolderGit2 size={15} /><span>{item.title}</span>{repo?.id === item.id && <span className="small-dot" />}</button>)}</div>
      <button className="sidebar-import" disabled={inFlight} onClick={() => importInput.current?.click()}><Upload size={14} />导入 workflow.json</button>
      <input ref={importInput} className="hidden" type="file" accept=".json,application/json" onChange={event => { const file = event.target.files?.[0]; if (file) void action('导入', async () => { const body = JSON.parse(await file.text()); const data = await api<{repo: Repo}>('/import', body); await refreshRepos(); acceptRepo(data.repo); setTab('studio'); notify('工作流导入成功') }); event.target.value = '' }} />
      <div className="sidebar-bottom"><div className="connection-card"><span className="pulse-dot" /><span>MCP Gateway</span><button className="icon-button" title="连接 MCP" onClick={() => open('connect')}><ArrowUpRight size={14} /></button><small>本地网关 · {health.provider === 'demo' ? '演示生成器' : 'HTTP 模型服务'}</small></div><button className="profile" onClick={() => open('connect')}><span className="avatar">C</span><span>Local Creator<small>本地创作空间</small></span><Settings2 size={16} /></button></div>
    </aside>
    <main className="main-shell">
      <header className="topbar"><div className="breadcrumbs"><span>工作空间</span><span>/</span><Film size={14} /><strong>{repo?.workflow.title || 'CineGit Studio'}</strong>{dirty && <span className="draft-badge">DRAFT</span>}</div><div className="topbar-actions"><span className="local-badge"><span className="small-dot" /> LOCAL FIRST</span><button className="icon-button" title="连接设置" onClick={() => open('connect')}><Settings2 size={17} /></button><span className="avatar small">C</span></div></header>
      {!repo || !draft ? <div className="empty-state"><Clapperboard size={40} /><h2>{notice?.error ? '工作区连接失败' : initialLoading ? '正在载入创作空间' : '创建你的第一部影片'}</h2><p>{notice?.error ? notice.text : initialLoading ? '首次启动正在生成真实演示视频，请稍候。' : '从一份可复用的分镜工作流开始。'}</p>{!initialLoading && !notice?.error ? <button className="button primary" onClick={() => open('new', '我的第一部影片')}><Plus size={15} />新建影片</button> : <button className="button" onClick={() => location.reload()}><RefreshCw size={15} />重新连接</button>}</div> : <>
      {tab === 'studio' && <>
        <div className="page-heading"><div><div className="eyebrow">THE CREATIVE REPOSITORY</div><h1>{draft.title}<span className="heading-period">.</span></h1><p>{draft.description}</p></div><div className="heading-actions"><select aria-label="当前分支" className="branch-select" disabled={inFlight || !!busy} value={repo.current_branch} onChange={event => { const name = event.target.value; void action('切换分支', async () => { const current = await saveDraft(); const data = await api<{repo: Repo}>(`/repos/${current.id}/checkout`, {name}); acceptRepo(data.repo); setMode('film') }) }}>{Object.keys(repo.branches).map(branch => <option key={branch}>{branch}</option>)}</select><button className="button" disabled={inFlight || !!busy} onClick={() => open('branch', 'explore/new')}><GitBranch size={15} />新分支</button><button className="button primary" disabled={inFlight || !!busy} onClick={() => open('commit', '调整分镜与创作参数')}><GitCommitHorizontal size={17} />{inFlight ? '渲染中…' : 'Commit & Render'}</button></div></div>
        <div className="studio-layout"><div className="studio-center">
          <section className="viewer-panel"><div className="panel-bar"><div className="panel-label"><span className="small-dot green-bg" />{mode === 'film' ? 'FILM PREVIEW' : 'LIVE ANIMATIC'}<span className="sub-label">{mode === 'film' ? '当前分支成片' : `分镜 ${String(selectedIndex + 1).padStart(2, '0')} · 关键帧运镜`}</span></div><div className="segmented"><button className={mode === 'film' ? 'active' : ''} onClick={() => setMode('film')}>成片</button><button className={mode === 'preview' ? 'active' : ''} onClick={() => setMode('preview')}>关键帧</button></div><button className="icon-button" aria-label="全屏预览" onClick={() => { const element = mode === 'film' ? video.current : document.querySelector('.preview-stage'); void element?.requestFullscreen() }}><Maximize2 size={14} /></button></div>
          <div className={`preview-stage motion-${selected?.params.camera_motion}`}>
            {mode === 'film' && repo.commit ? <video ref={video} key={repo.commit.stats.video_url} src={repo.commit.stats.video_url} poster={repo.commit.nodes.find(node => node.preview_img)?.preview_img} controls playsInline onTimeUpdate={event => setPlayhead(event.currentTarget.currentTime)} /> : mode === 'preview' ? <MixedPlayer clips={timeline.map(node => { const plan = repo.plan.find(item => item.node_id === node.node_id); return {shot: node, video: !localDirty && plan?.cache_hit && preview?.node_id !== node.node_id ? plan?.artifact_mp4 : undefined, image: preview?.node_id === node.node_id ? preview.src : plan?.preview_img} })} selectedId={selected?.node_id} select={setSelectedId} /> : <div className="stage-empty"><Clapperboard size={40} /><strong>故事从这一帧开始</strong><p>{mode === 'film' ? '提交工作流，生成你的第一版成片' : '点击「关键帧预览」查看当前分镜'}</p></div>}
            <div className="stage-corner top-left" /><div className="stage-corner bottom-right" />
          </div><div className="viewer-footer"><div><span className="mono">{mode === 'film' ? time(playhead) : '00:00'} <span className="muted">/ {time(mode === 'film' ? repo.commit?.stats.duration || totalDuration : selected?.params.duration || 3)}</span></span><span className="format-tag">1280 × 720</span><span className="muted small-text">24 FPS</span></div><div><span className="small-text muted">{repo.commit?.stats.fallback_nodes ? `演示回退 · ${repo.commit.stats.fallback_nodes} 个节点` : health.provider === 'demo' ? '离线程序化演示画面' : '外部模型生成'}</span>{repo.commit && <a className="icon-button" href={repo.commit.stats.video_url} download title="下载成片"><Download size={16} /></a>}</div></div></section>
          <section className="timeline-panel"><div className="section-heading"><div><Film size={15} /><strong>分镜时间轴</strong><span className="count-pill">{timeline.length}</span></div><div><span className="small-text muted">点击分镜编辑</span><button className="text-button" disabled={inFlight} onClick={() => { setNewDependencies([]); open('node', '新的镜头', '电影级镜头，描述你的画面') }}><Plus size={14} />添加分镜</button></div></div><div className="timeline-ruler"><span>00:00</span><span>{time(totalDuration / 3)}</span><span>{time(totalDuration * 2 / 3)}</span><span>{time(totalDuration)}</span></div><div className="filmstrip">{timeline.map((node, index) => { const plan = repo.plan.find(item => item.node_id === node.node_id); return <button key={node.node_id} className={`film-cell ${selected?.node_id === node.node_id ? 'selected' : ''}`} onClick={() => { setSelectedId(node.node_id); if (mode === 'film' && video.current) video.current.currentTime = timeline.slice(0, index).reduce((sum, item) => sum + item.params.duration, 0) }} style={{flexGrow: node.params.duration}}>{plan?.preview_img ? <img src={plan.preview_img} alt="" /> : <div className="film-placeholder"><Film size={20} /></div>}<span className="film-index">{String(index + 1).padStart(2, '0')}</span><span className={`cache-indicator ${plan?.cache_hit ? 'cached' : ''}`}>{plan?.cache_hit ? <Zap size={10} /> : <CircleDot size={10} />}</span><div className="film-caption"><strong>{node.title}</strong><span>{node.params.duration}s</span></div><div className="film-track" /></button> })}</div><div className="timeline-legend"><span><span className="legend-dot green-bg" />缓存可复用</span><span><span className="legend-dot orange-bg" />需要渲染</span><span className="timeline-hint"><ShieldCheck size={12} />固定种子，可重复创作</span></div></section>
          <section className="dag-panel"><div className="section-heading"><div><Network size={15} /><strong>工作流 DAG</strong><span className="count-pill">{draft.nodes.length} NODES</span></div><button className="text-button" onClick={() => open('recording')}><Radio size={13} className="green" />MCP 录制日志<ArrowUpRight size={13} /></button></div><div className="dag-canvas"><ReactFlow nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes} colorMode="dark" fitView fitViewOptions={{padding: .16, maxZoom: .9}} onNodeClick={(_, node) => setSelectedId(node.id)} nodesDraggable={false} nodesConnectable={false} minZoom={.2} proOptions={{hideAttribution: true}}><Background color="#343d36" gap={18} /><Controls showInteractive={false} /></ReactFlow>{flowEdges.length === 0 && <div className="dag-caption">独立分镜并行建模 · 在右侧设置上游依赖</div>}</div></section>
        </div><aside className="inspector"><div className="inspector-title"><Settings2 size={16} /><strong>分镜设置</strong><span className="mono muted">{String(selectedIndex + 1).padStart(2, '0')}</span></div>{selected && <fieldset disabled={inFlight || !!busy}><div className="inspector-section"><div className="node-title-row"><span className="node-symbol"><Film size={18} /></span><div><input className="title-input" aria-label="分镜名称" value={selected.title} onChange={event => editNode({title: event.target.value})} /><code>{selected.node_id}</code></div><button className="icon-button danger" title="删除分镜" disabled={draft.nodes.length <= 1 || (selected.mcp_tool === 'mcp_video_gen' && timeline.length <= 1)} onClick={() => { if (draft.nodes.some(node => node.depends_on.includes(selected.node_id))) { notify('请先解除下游节点对此分镜的依赖', true); return } const remaining = draft.nodes.filter(node => node.node_id !== selected.node_id); setDraft({...draft, nodes: remaining}); setSelectedId(remaining[0].node_id) }}><Trash2 size={14} /></button></div><div className="provider-line"><span className="provider-icon">{health.provider === 'demo' ? 'D' : '↗'}</span><span>{health.provider === 'demo' ? 'CineGit Local' : 'HTTP Provider'}</span><span className="tag">{tools[selected.mcp_tool]}</span></div></div>
          <div className="inspector-section"><label className="field-label" htmlFor="prompt">PROMPT <span>支持 {'{{变量}}'}</span></label><textarea id="prompt" className="prompt-input" rows={6} value={selected.prompt_template} onChange={event => editNode({prompt_template: event.target.value})} /><div className="prompt-foot"><span>{selected.prompt_template.length} characters</span><button className="text-button" onClick={() => void action('检测变量', async () => { const current = await saveDraft(); const data = await api<{suggestions: typeof suggestions}>(`/repos/${current.id}/distill-suggestions`); setSuggestions(data.suggestions); open('distill', 'subject', data.suggestions[0]?.value || '') })}><WandSparkles size={12} />变量蒸馏</button></div><label className="field-label" htmlFor="seed">SEED <span><ShieldCheck size={11} />确定性种子</span></label><div className="seed-input"><input id="seed" type="number" min={0} max={2147483647} value={selected.params.seed} onChange={event => editNode({params: {...selected.params, seed: Number(event.target.value)}})} /><button className="icon-button" title="随机种子" onClick={() => editNode({params: {...selected.params, seed: Math.floor(Math.random() * 2147483647)}})}><RefreshCw size={14} /></button></div><div className="form-columns"><div><label className="field-label" htmlFor="motion">运镜方式</label><select id="motion" value={selected.params.camera_motion} onChange={event => editNode({params: {...selected.params, camera_motion: event.target.value}})}>{Object.entries(motions).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div><div><label className="field-label" htmlFor="duration">时长 / 秒</label><input id="duration" type="number" min="0.5" max="20" step="0.5" value={selected.params.duration} onChange={event => editNode({params: {...selected.params, duration: Number(event.target.value)}})} /></div></div><details className="dependencies"><summary>上游依赖 <span>{selected.depends_on.length}</span></summary>{draft.nodes.filter(node => node.node_id !== selected.node_id).map(node => <label key={node.node_id}><input type="checkbox" checked={selected.depends_on.includes(node.node_id)} onChange={event => editNode({depends_on: event.target.checked ? [...selected.depends_on, node.node_id] : selected.depends_on.filter(id => id !== node.node_id)})} />{node.title}</label>)}</details><button className="button preview-button" onClick={() => void action('关键帧预览', showPreview)}><Sparkles size={15} />{busy === '关键帧预览' ? '生成中…' : '关键帧预览'}<span>TIER 01</span></button></div>
          <div className="inspector-section variables-section"><div className="section-heading"><div><Code2 size={14} /><strong>全局变量</strong></div><button className="icon-button" title="添加变量" onClick={() => open('variable', '', '')}><Plus size={14} /></button></div>{Object.entries(draft.variables).map(([name, value]) => <label className="variable-field" key={name}><span>{'{{'}<strong>{name}</strong>{'}}'}</span><input aria-label={`变量 ${name}`} value={value} onChange={event => { setDraft({...draft, variables: {...draft.variables, [name]: event.target.value}}); setPreview(null) }} /></label>)}</div>
          <div className="inspector-section cache-card"><div><Zap size={16} className="green" /><strong>增量渲染引擎</strong><span className="tag green">MERKLE DAG</span></div><p>只重绘变化的镜头，保留每一次灵感。</p><div className="cache-stat"><span>当前可复用节点</span><strong>{repo.plan.filter(node => node.cache_hit).length}<small> / {repo.plan.length}</small></strong></div><div className="meter"><span style={{width: `${repo.plan.filter(node => node.cache_hit).length / repo.plan.length * 100}%`}} /></div><div className="hash-line"><span>NODE HASH</span><code>{localDirty ? '保存后重新计算' : planned?.node_hash.slice(0, 16)}</code></div></div>
          <div className="inspector-save"><button className="button full" onClick={() => void action('保存草稿', async () => { await saveDraft(); notify('草稿已保存，缓存计划已更新') })}><Save size={14} />{busy === '保存草稿' ? '保存中…' : '保存草稿'}{localDirty && <span className="small-dot orange-bg" />}</button><a href={`/api/repos/${repo.id}/export`} className="text-button"><FileCode2 size={13} />导出 workflow.json</a></div></fieldset>}</aside></div>
      </>}
      {tab === 'history' && <><div className="page-heading"><div><div className="eyebrow">EVERY FRAME HAS A HISTORY</div><h1>每一次探索，都有迹可循<span className="heading-period">.</span></h1><p>比较画面与参数，把最好的镜头带回你的故事。</p></div><button className="button" disabled={inFlight} onClick={() => open('branch', 'explore/new', selectedCommit)}><GitBranch size={15} />从所选提交创建分支</button></div><div className="history-layout"><section className="history-graph"><div className="section-heading"><div><GitBranch size={16} /><strong>版本演进</strong></div><span className="tag">{repo.commits.length} COMMITS</span></div>{repo.commits.length ? <div className="commit-canvas"><ReactFlow nodes={commitNodes} edges={commitEdges} nodeTypes={nodeTypes} fitView colorMode="dark" minZoom={.2} maxZoom={1.1} nodesDraggable={false} nodesConnectable={false} onNodeClick={(_, node) => { setSelectedCommit(node.id); setDiffLeft(node.id) }} proOptions={{hideAttribution: true}}><Background color="#343d36" gap={18} /><Controls showInteractive={false} /></ReactFlow></div> : <div className="empty-state"><GitCommitHorizontal size={30} /><p>完成首次 Commit 后，版本树将显示在这里。</p></div>}{selectedHistory && <div className="history-detail"><code>{selectedHistory.hash.slice(0, 12)}</code><h3>{selectedHistory.message}</h3><p>{selectedHistory.workflow.author} · {new Date(selectedHistory.created_at).toLocaleString('zh-CN')}</p><div className="history-metrics"><span><strong>{selectedHistory.stats.cache_hit_rate}%</strong>缓存命中</span><span><strong>{selectedHistory.stats.concat_ms}ms</strong>流拷贝拼接</span><span><strong>${selectedHistory.stats.estimated_saved_usd.toFixed(2)}</strong>估算节省</span></div><button className="button full" disabled={inFlight || !!busy} onClick={() => open('revert', `回滚至 ${selectedCommit.slice(0, 8)}`)}><RotateCcw size={14} />回滚为新提交</button></div>}</section><section className="diff-panel"><div className="section-heading"><div><GitCompareArrows size={17} /><strong>Visual Diff</strong></div><span className="tag">{diff?.changed_count || 0} NODES CHANGED</span></div>{repo.commits.length ? <><div className="diff-selectors"><label>BEFORE<select value={diffLeft} onChange={event => setDiffLeft(event.target.value)}>{repo.commits.map(commit => <option value={commit.hash} key={commit.hash}>{commit.hash.slice(0, 7)} · {commit.message}</option>)}</select></label><ArrowRight size={17} /><label>AFTER<select value={diffRight} onChange={event => setDiffRight(event.target.value)}><option value="working">当前工作区</option>{repo.commits.map(commit => <option value={commit.hash} key={commit.hash}>{commit.hash.slice(0, 7)} · {commit.message}</option>)}</select></label></div>{diff && <><div className="diff-videos"><div>{diff.left.stats?.video_url ? <video ref={leftVideo} key={diff.left.hash} src={diff.left.stats.video_url} controls playsInline onPlay={() => syncVideos('play')} onPause={() => syncVideos('pause')} onSeeked={() => syncVideos('seek')} onTimeUpdate={() => { if (leftVideo.current && rightVideo.current && !leftVideo.current.paused && Math.abs(leftVideo.current.currentTime - rightVideo.current.currentTime) > .25) rightVideo.current.currentTime = leftVideo.current.currentTime }} /> : <div className="video-placeholder">未生成视频</div>}<span>{diff.left.hash.slice(0, 8)}</span></div><div>{diff.right.stats?.video_url ? <video ref={rightVideo} key={diff.right.hash} src={diff.right.stats.video_url} playsInline muted /> : <div className="video-placeholder"><Clapperboard size={28} /><span>工作区关键帧</span><small>Commit 后可同步比较成片</small></div>}<span>{diff.right.hash === 'working' ? 'WORKING TREE' : diff.right.hash.slice(0, 8)}</span></div></div><p className="diff-caption"><Play size={12} />使用左侧播放器控制双栏同步播放、暂停和定位</p><div className="diff-rows">{diff.changes.map(change => <div key={change.node_id} className={`diff-row ${change.status}`}><div className="diff-row-heading"><label><input type="checkbox" disabled={diffRight === 'working' || change.status === 'removed' || change.status === 'unchanged'} checked={pick.includes(change.node_id)} onChange={event => setPick(event.target.checked ? [...pick, change.node_id] : pick.filter(id => id !== change.node_id))} /><strong>{change.title}</strong><code>{change.node_id}</code></label><span className={`status-tag ${change.status}`}>{({unchanged: '缓存复用', modified: '已修改', added: '新增', removed: '删除'})[change.status]}</span></div>{change.fields.map(field => <div key={field.field} className="field-diff"><span>{field.field}</span><div><pre className="before">− {fmt(field.before)}</pre><pre className="after">+ {fmt(field.after)}</pre></div></div>)}{change.status === 'modified' && !change.fields.length && <p className="small-text muted">上游依赖发生变化，节点哈希已更新。</p>}{change.status === 'unchanged' && <div className="unchanged-note"><Zap size={12} /><code>{change.after?.node_hash.slice(0, 16)}</code><span>无需重新生成</span></div>}{['added', 'removed'].includes(change.status) && <pre>{fmt((change.after || change.before)?.prompt_template)}</pre>}</div>)}</div><div className="diff-actions"><span className="small-text muted">Cherry-pick 会包含所选镜头的上游依赖与引用变量。</span><button className="button primary" disabled={!pick.length || inFlight || !!busy} onClick={() => void action('合并镜头', async () => { const current = await saveDraft(); const data = await api<{repo: Repo}>(`/repos/${current.id}/cherry-pick`, {commit: diffRight, node_ids: pick, revision: current.revision}); acceptRepo(data.repo); setTab('studio'); notify('镜头已合入草稿，Commit 即可生成新版本') })}><GitFork size={15} />合入 {pick.length || ''} 个镜头</button></div></>}</> : <div className="empty-state"><GitCompareArrows size={30} /><p>暂无提交可比较</p></div>}</section></div></>}
      {tab === 'market' && <div className="market-page"><div className="market-hero"><div className="eyebrow">THE WORKFLOW EXCHANGE</div><div className="market-heading"><h1>好故事，值得被 Fork<span className="heading-period">.</span></h1><button className="button primary" disabled={!repo.head || inFlight} onClick={() => { setPrice(0); open('publish', draft.title, draft.description) }}><Plus size={16} />发布工作流</button></div><p>带走的不只是提示词，还有从第一帧到最终成片的完整创作路径。</p><div className="market-meta"><span><Code2 size={15} />可执行工作流</span><span><ShieldCheck size={15} />参数与种子完整保留</span><span><GitFork size={15} />一键 Fork，自由演绎</span></div></div><div className="market-toolbar"><div><strong>精选创作配方</strong><span className="count-pill">{market.length}</span></div><label className="search-field"><Search size={15} /><input aria-label="搜索工作流" placeholder="搜索风格、故事或创作者…" value={query} onChange={event => setQuery(event.target.value)} /></label></div><div className="market-grid">{market.filter(item => [item.title, item.description, item.author, ...item.tags].join(' ').toLowerCase().includes(query.toLowerCase())).map((listing, index) => <article className="market-card" key={listing.id}><div className="market-cover"><img src={listing.preview_img} alt={listing.title} /><span className="market-index">RECIPE / {String(index + 1).padStart(3, '0')}</span><span className="market-duration"><Film size={12} />{listing.duration}s · {listing.node_count} nodes</span><button className="cover-play" aria-label={`预览 ${listing.title}`} onClick={() => { setPaidListing(listing); open('market-preview') }}><Play size={21} fill="currentColor" /></button></div><div className="market-content"><div className="market-author"><span className="avatar mini">C</span>{listing.author}<span><GitFork size={12} />{listing.forks}</span></div><h2>{listing.title}</h2><p>{listing.description}</p><div className="tags">{listing.tags.map(tag => <span key={tag}>{tag}</span>)}</div><div className="market-card-footer"><div><strong>{listing.price ? `$${listing.price}` : '免费'}</strong><span>{listing.price ? '演示定价 · 不收款' : listing.license}</span></div><button className="button" disabled={!!busy || inFlight} onClick={() => { if (listing.price) { setPaidListing(listing); open('purchase') } else void action('Fork', () => fork(listing)) }}><GitFork size={14} />Fork 工作流</button></div></div></article>)}</div>{market.length > 0 && !market.some(item => [item.title, item.description, item.author, ...item.tags].join(' ').toLowerCase().includes(query.toLowerCase())) && <div className="empty-state"><Search size={30} /><p>没有匹配的工作流</p></div>}<div className="market-footnote"><Store size={15} />本地社区市场演示 · 发布绑定不可变提交 · 付费流程仅生成演示记录，不处理真实付款</div></div>}
      <footer className="statusbar"><div><span className="pulse-dot" />{inFlight ? `渲染 ${job?.progress}/${job?.total} · ${job?.message}` : '所有灵感，皆可追溯'}{inFlight && <LoaderCircle size={12} className="spin" />}</div><div><span><GitBranch size={12} />{repo.current_branch}</span><span><GitCommitHorizontal size={12} />{repo.head?.slice(0, 7) || 'NO COMMITS'}</span><span><Zap size={12} />{latestStats?.cache_hit_rate || 0}% cache</span><span>CINEGIT v0.1</span></div></footer>
      </>}
    </main>
    {notice && <div className={`toast ${notice.error ? 'error' : ''}`} role={notice.error ? 'alert' : 'status'}>{notice.error ? <CircleDot size={17} /> : <Check size={17} />}<span>{notice.text}</span><button className="icon-button" aria-label="关闭通知" onClick={() => setNotice(null)}><X size={15} /></button></div>}
    {modal && <Modal title={({commit: '把这一版灵感，提交下来', branch: '开启一条新的创作分支', new: '新的故事，从这里开始', publish: '分享你的创作配方', distill: '把重复设定，变成变量', variable: '添加全局变量', node: '为故事添加一个节点', revert: '回到那个版本，继续创作', purchase: '演示购买与 Fork', connect: '连接你的创作 Agent', recording: 'MCP 工作流录制', 'market-preview': paidListing?.title || '预览'})[modal] || ''} close={closeModal} subtitle={modal === 'commit' ? '未变化的节点将直接读取历史缓存，只有变化的镜头需要重新渲染。' : modal === 'revert' ? '会创建一个新的回滚提交，保留完整版本历史。' : undefined}>
      {['commit', 'branch', 'new', 'publish', 'distill', 'variable', 'node', 'revert'].includes(modal) && <form onSubmit={event => { event.preventDefault(); void action('提交', confirmModal) }}><label className="modal-field">{({commit: '提交说明', branch: '分支名称', new: '影片名称', publish: '配方标题', distill: '变量名', variable: '变量名', node: '节点名称', revert: '回滚说明'})[modal]}<input required maxLength={modal === 'commit' ? 300 : 120} value={modalText} onChange={event => setModalText(event.target.value)} placeholder={['variable', 'distill'].includes(modal) ? '例如 protagonist' : ''} /></label>{modal === 'branch' && <label className="modal-field">起始提交<select value={modalExtra} onChange={event => setModalExtra(event.target.value)}><option value="">当前分支 HEAD</option>{repo?.commits.map(commit => <option key={commit.hash} value={commit.hash}>{commit.hash.slice(0, 8)} · {commit.message}</option>)}</select><small className="muted">新分支从提交快照建立；原分支草稿会保留。</small></label>}{modal === 'node' && <><label className="modal-field">工具<select value={newTool} onChange={event => setNewTool(event.target.value)}>{Object.entries(tools).map(([name, label]) => <option key={name} value={name}>{label}</option>)}</select></label><label className="modal-field">上游依赖<select multiple value={newDependencies} onChange={event => setNewDependencies([...event.target.selectedOptions].map(option => option.value))}>{draft?.nodes.map(node => <option key={node.node_id} value={node.node_id}>{node.title}</option>)}</select></label></>}{['publish', 'distill', 'variable', 'node'].includes(modal) && <label className="modal-field">{modal === 'publish' ? '配方介绍' : modal === 'node' ? '提示词' : '原始内容'}<textarea required={modal !== 'variable'} rows={3} value={modalExtra} onChange={event => setModalExtra(event.target.value)} /></label>}{modal === 'distill' && <><div className="info-box"><WandSparkles size={17} /><span>离线模式使用重复短语检测。确认原文后，会在所有提示词中精确替换为 {'{{变量名}}'}。</span></div>{suggestions.map(item => <button type="button" key={item.name} className="suggestion" onClick={() => { setModalText(item.name); setModalExtra(item.value) }}>{item.value}<span>{item.occurrences} 处</span></button>)}</>}{modal === 'publish' && <><label className="modal-field">演示价格 / USD<input type="number" min={0} max={9999} value={price} onChange={event => setPrice(Number(event.target.value))} /></label><div className="info-box"><ShieldCheck size={16} /><span>发布当前分支已提交的快照。当前市场仅提供本地演示交易，平台费率 15%，不处理真实付款。</span></div></>}{modal === 'commit' && repo && <div className="commit-summary"><span><Zap size={17} /><strong>{repo.plan.filter(node => node.cache_hit).length}/{repo.plan.length}</strong>保存前可复用</span><span><GitBranch size={17} /><strong>{repo.current_branch}</strong>目标分支</span></div>}<div className="modal-actions"><button type="button" className="button" onClick={() => setModal('')}>取消</button><button className="button primary" disabled={!!busy || inFlight} type="submit">{busy ? <LoaderCircle size={15} className="spin" /> : modal === 'commit' ? <GitCommitHorizontal size={16} /> : <ArrowRight size={15} />}{modal === 'commit' ? '提交并增量渲染' : '确认'}</button></div></form>}
      {modal === 'connect' && <><div className="connection-status"><span className="pulse-dot" />后端在线 · {health.provider === 'demo' ? '本地演示生成器' : 'HTTP 模型网关'} · FFmpeg {health.ffmpeg ? '可用' : '缺失'}</div><p className="muted">在 Claude Desktop 或支持 MCP 的客户端中添加以下配置。将路径替换为此项目的绝对路径。</p><pre className="config-code">{JSON.stringify({mcpServers: {cinegit: {command: 'uv', args: ['--directory', '/absolute/path/to/CineGit', 'run', 'python3', '-m', 'cinegit.mcp_server']}}}, null, 2)}</pre><div className="info-box"><Terminal size={17} /><span>通过 cinegit_generate 调用的工具会自动录制。图像、视频、脚本与声音工具共享同一个版本化 DAG。</span></div><div className="modal-actions"><a href="/docs" target="_blank" rel="noreferrer" className="button"><Code2 size={14} />API 文档</a><button className="button primary" onClick={() => void action('复制', async () => { await navigator.clipboard.writeText(JSON.stringify({mcpServers: {cinegit: {command: 'uv', args: ['--directory', '/absolute/path/to/CineGit', 'run', 'python3', '-m', 'cinegit.mcp_server']}}}, null, 2)); notify('配置已复制，请替换项目绝对路径') })}><Copy size={14} />复制配置</button></div></>}
      {modal === 'recording' && <><div className="info-box"><Radio size={17} /><span>以下记录来自真实的仓库操作。使用 MCP cinegit_generate 后，会出现工具输入、输出与资产哈希记录。</span></div><div className="event-list">{repo?.events.map(event => <div key={event.id}><span className="event-dot" /><div><strong>{event.action}</strong><small>{new Date(event.created_at).toLocaleString('zh-CN')}</small><pre>{JSON.stringify(event.details, null, 2)}</pre></div></div>)}</div></>}
      {modal === 'market-preview' && paidListing && <video className="market-modal-video" src={paidListing.video_url} controls autoPlay playsInline />}
      {modal === 'purchase' && paidListing && <><p className="muted">{paidListing.title}</p><div className="purchase-receipt"><div><span>配方演示价格</span><strong>${paidListing.price.toFixed(2)}</strong></div><div><span>创作者份额 (85%)</span><span>${(paidListing.price * .85).toFixed(2)}</span></div><div><span>平台份额 (15%)</span><span>${(paidListing.price * .15).toFixed(2)}</span></div></div><div className="info-box"><ShieldCheck size={17} /><span>这是本地交易演示，不会收取费用。确认后会记录演示购买并 Fork 工作流，原许可证与来源会保留。</span></div><div className="modal-actions"><button className="button" onClick={() => setModal('')}>取消</button><button className="button primary" disabled={!!busy} onClick={() => void action('演示购买', confirmModal)}><GitFork size={15} />确认演示购买并 Fork</button></div></>}
    </Modal>}
    {busy && <div className="busy-indicator" role="status"><LoaderCircle size={14} className="spin" />{busy}…</div>}
  </div>
}
