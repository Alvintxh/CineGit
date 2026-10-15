import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import type { Repo } from '../src/types'
import { api } from '../src/api'
import App from '../src/App'

vi.mock('../src/api', () => ({api: vi.fn()}))
vi.mock('@xyflow/react', () => ({ReactFlow: ({children}: {children: ReactNode}) => <div aria-label="图画布">{children}</div>, Background: () => null, Controls: () => null, Handle: () => null, Position: {Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom'}}))

function repository(): Repo {
  const shot = {node_id: 'shot_01', title: '初始镜头', mcp_tool: 'mcp_video_gen', prompt_template: '{{protagonist}}走入城市', params: {seed: 42, duration: 3, camera_motion: 'zoom_in'}, depends_on: []}
  return {id: 'repo-1', title: '测试影片', revision: 0, current_branch: 'main', branches: {main: null, explore: null}, workflow: {title: '测试影片', description: '故事描述', author: '@creator', license: 'CC-BY-4.0', variables: {protagonist: '少女'}, nodes: [shot]}, plan: [{...shot, resolved_prompt: '少女走入城市', node_hash: 'abc123', cache_hit: false}], head: null, commit: null, commits: [], dirty: true, jobs: [], events: []}
}

let current: Repo
const mockApi = vi.mocked(api)
beforeEach(() => {
  current = repository()
  mockApi.mockImplementation(async (path, body) => {
    if (path === '/repos' && body === undefined) return {repos: [{id: current.id, title: current.title, current_branch: current.current_branch}]}
    if (path === '/health') return {provider: 'demo', ffmpeg: true}
    if (path === '/repos' && body === null) return {repo: structuredClone({...current, id: 'new-repo'})}
    if (path.endsWith('/draft')) { const data = body as {workflow: Repo['workflow']; revision: number}; current = {...current, workflow: data.workflow, revision: data.revision + 1}; return {repo: structuredClone(current)} }
    if (path.endsWith('/checkout')) { current = {...current, current_branch: (body as {name: string}).name, revision: current.revision + 1}; return {repo: structuredClone(current)} }
    if (path.includes('/preview/')) return {preview_img: '/media/preview.webp'}
    if (path.startsWith('/repos/')) return {repo: structuredClone(current)}
    throw new Error(`Unexpected path: ${path}`)
  })
})

describe('Studio user flows', () => {
  it('saves edited variables and prompt using the current revision', async () => {
    const user = userEvent.setup()
    render(<App />)
    const prompt = await screen.findByLabelText(/PROMPT/)
    await user.clear(prompt)
    await user.type(prompt, '新的雨夜镜头')
    const variable = screen.getByLabelText('变量 protagonist')
    await user.clear(variable)
    await user.type(variable, '橘猫')
    await user.click(screen.getByRole('button', {name: '保存草稿'}))
    await waitFor(() => expect(current.workflow.nodes[0].prompt_template).toBe('新的雨夜镜头'))
    expect(current.workflow.variables.protagonist).toBe('橘猫')
    expect(current.revision).toBe(1)
    expect(await screen.findByText('草稿已保存，缓存计划已更新')).toBeTruthy()
  })

  it('creates a repository with an optional request body then names it', async () => {
    const user = userEvent.setup()
    render(<App />)
    await screen.findByLabelText(/PROMPT/)
    await user.click(screen.getByTitle('新建影片'))
    const dialog = screen.getByRole('dialog')
    const name = within(dialog).getByLabelText('影片名称')
    await user.clear(name)
    await user.type(name, '我的第二部片')
    await user.click(within(dialog).getByRole('button', {name: '确认'}))
    await waitFor(() => expect(mockApi).toHaveBeenCalledWith('/repos', null))
    await waitFor(() => expect(current.workflow.title).toBe('我的第二部片'))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('captures selected branch before awaiting an unsaved draft', async () => {
    const user = userEvent.setup()
    render(<App />)
    const prompt = await screen.findByLabelText(/PROMPT/)
    await user.type(prompt, '，日落')
    await user.selectOptions(screen.getByLabelText('当前分支'), 'explore')
    await waitFor(() => expect(current.current_branch).toBe('explore'))
    expect(mockApi).toHaveBeenCalledWith('/repos/repo-1/checkout', {name: 'explore'})
    expect(current.workflow.nodes[0].prompt_template).toContain('日落')
  })

  it('saves before preview and provides the mixed player controls', async () => {
    const user = userEvent.setup()
    render(<App />)
    const prompt = await screen.findByLabelText(/PROMPT/)
    await user.type(prompt, '，暖色')
    await user.click(screen.getByRole('button', {name: /关键帧预览/}))
    expect(await screen.findByRole('button', {name: '播放混合分镜'})).toBeTruthy()
    expect(screen.getByAltText('初始镜头关键帧').getAttribute('src')).toBe('/media/preview.webp')
    const calls = mockApi.mock.calls.map(call => call[0])
    expect(calls.indexOf('/repos/repo-1/draft')).toBeLessThan(calls.indexOf('/repos/repo-1/preview/shot_01'))
  })
})
