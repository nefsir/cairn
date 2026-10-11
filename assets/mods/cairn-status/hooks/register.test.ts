import { test, expect, mock } from 'claude-code/testing'
import type { On, FsEntry } from 'claude-code'

const Q = '/h/.claude/cairn/queue'

type Files = Record<string, Record<string, { mtimeMs: number; body?: object }>>

function world(on: On, files: Files, store: Record<string, unknown>) {
  const statuses: (string | undefined)[] = []
  const toasts: string[] = []
  const saved: unknown[] = []
  mock.env(on, { HOME: '/h' })
  const kept: Record<string, unknown> = { ...store }
  on('store.get', ($, e) => ({ value: kept[e.key] }))
  on('store.set', ($, e) => { kept[e.key] = e.value; saved.push(e.value); return { value: undefined } })
  const clock = mock.clock(on, { now: 50_000 })
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('fs.list', ($, e) => {
    const dir = files[e.path.slice(Q.length + 1)]
    if (dir === undefined) throw new Error(`ENOENT ${e.path}`)
    return { value: Object.entries(dir).map(([name, f]): FsEntry =>
      ({ name, kind: 'file', size: 1, mtimeMs: f.mtimeMs, isLink: false })) }
  })
  on('fs.read', ($, e) => {
    const [dir, name] = e.path.slice(Q.length + 1).split('/')
    return { value: JSON.stringify(files[dir ?? '']?.[name ?? '']?.body ?? {}) }
  })
  on('ui.status', ($, e) => { statuses.push(e.text); return { value: undefined } })
  on('ui.toast', ($, e) => { toasts.push(e.text); return { value: undefined } })
  return { statuses, toasts, clock, saved }
}

const start = ($: any) => $.session.start({ cwd: '/x', surface: 'terminal', isInteractive: true })

test('shows non-zero counters with a failed marker', async ($, on) => {
  const w = world(on, {
    pending: { 'a.json': { mtimeMs: 1 } },
    running: {},
    failed: { 'b.json': { mtimeMs: 1 } },
    done: {},
  }, { lastSeenMs: 10 })
  await start($)
  expect(w.statuses.at(-1)).toBe('cairn review: 1 pending · ⚠ 1 failed')
})

test('clears the status line when the queue is idle or missing', async ($, on) => {
  const w = world(on, {}, { lastSeenMs: 10 })
  await start($)
  expect(w.statuses.at(-1)).toBe(undefined)
})

test('toasts a new review that changed skills and a new failure, not old or empty ones', async ($, on) => {
  const w = world(on, {
    done: {
      'old.json': { mtimeMs: 5, body: { changed_skills: ['x'], transcript_path: '/p/old.jsonl' } },
      'noop.json': { mtimeMs: 20, body: { changed_skills: [], transcript_path: '/p/noop.jsonl' } },
      'new.json': { mtimeMs: 30, body: { changed_skills: ['a', 'b'], transcript_path: '/p/3d3b8570-xx.jsonl' } },
    },
    failed: { 'f.json': { mtimeMs: 40, body: { why: 'timeout', transcript_path: '/p/abcdef12-yy.jsonl' } } },
  }, { lastSeenMs: 10 })
  await start($)
  expect(w.toasts.join('\n')).toContain('review changed skills: a, b (3d3b8570)')
  expect(w.toasts.join('\n')).toContain('review failed (abcdef12): timeout')
  expect(w.toasts.join('\n')).not.toContain('x')
  expect(w.toasts.length).toBe(1)
  expect(w.saved.at(-1)).toBe(40)
})

test('first run only sets the watermark and does not replay history', async ($, on) => {
  const w = world(on, {
    done: { 'new.json': { mtimeMs: 30, body: { changed_skills: ['a'] } } },
  }, {})
  await start($)
  expect(w.toasts).toEqual([])
  expect(w.saved.at(-1)).toBe(50_000)
})

test('refreshes on a timer and toasts only once per entry', async ($, on) => {
  const failed: Files[string] = {}
  const files: Files = { failed }
  const w = world(on, files, { lastSeenMs: 10 })
  await start($)
  failed['f.json'] = { mtimeMs: 60, body: { why: 'rc=1', transcript_path: '/p/s1.jsonl' } }
  await w.clock.advance(60_000)
  await w.clock.advance(60_000)
  expect(w.toasts.length).toBe(1)
  expect(w.statuses.at(-1)).toBe('cairn review: ⚠ 1 failed')
})
