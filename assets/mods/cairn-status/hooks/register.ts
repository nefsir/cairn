import type { Register, EngineInterface } from 'claude-code'

// Mirrors the cairn review queue (~/.claude/cairn/queue) in the status line and
// toasts the two outcomes worth interrupting for: a failed review and a review
// that changed skills. `lastSeenMs` in $.store is the mtime watermark, so a
// review that finished between sessions is announced in the next one.

const REFRESH_MS = 60_000
const SEEN = 'lastSeenMs'

type Entry = { changed_skills?: string[]; why?: string; transcript_path?: string }

async function jsonFiles($: EngineInterface, dir: string) {
  try {
    return (await $.fs.list(dir)).filter(f => f.kind === 'file' && f.name.endsWith('.json'))
  } catch {
    return []
  }
}

async function readEntry($: EngineInterface, path: string): Promise<Entry> {
  try {
    return JSON.parse(String(await $.fs.read(path))) as Entry
  } catch {
    return {}
  }
}

function sessionOf(e: Entry, file: string) {
  const base = (e.transcript_path ?? file).split('/').pop() ?? file
  return base.replace(/\.jsonl?$/, '').slice(0, 8)
}

export function statusText(pending: number, running: number, failed: number) {
  const parts = [
    pending ? `${pending} pending` : '',
    running ? `${running} running` : '',
    failed ? `⚠ ${failed} failed` : '',
  ].filter(Boolean)
  return parts.length ? `cairn review: ${parts.join(' · ')}` : undefined
}

async function refresh($: EngineInterface) {
  const home = await $.env.get('HOME')
  const queue = `${home}/.claude/cairn/queue`
  const [pending, running, failed, done] = await Promise.all([
    jsonFiles($, `${queue}/pending`),
    jsonFiles($, `${queue}/running`),
    jsonFiles($, `${queue}/failed`),
    jsonFiles($, `${queue}/done`),
  ])
  $.ui.status(statusText(pending.length, running.length, failed.length))

  const seen = await $.store.get(SEEN)
  if (typeof seen !== 'number') {
    await $.store.set(SEEN, await $.clock.now())
    return
  }

  let watermark = seen
  const lines: string[] = []
  for (const [dir, files] of [['done', done], ['failed', failed]] as const) {
    for (const f of files.filter(f => f.mtimeMs > seen).sort((a, b) => a.mtimeMs - b.mtimeMs)) {
      watermark = Math.max(watermark, f.mtimeMs)
      const e = await readEntry($, `${queue}/${dir}/${f.name}`)
      if (dir === 'failed') {
        lines.push(`cairn: review failed (${sessionOf(e, f.name)}): ${e.why || 'no reason given'}`)
      } else if (e.changed_skills?.length) {
        lines.push(`cairn: review changed skills: ${e.changed_skills.join(', ')} (${sessionOf(e, f.name)})`)
      }
    }
  }
  if (lines.length) $.ui.toast(lines.join('\n'), { timeoutMs: 10_000 })
  if (watermark > seen) await $.store.set(SEEN, watermark)
}

async function safeRefresh($: EngineInterface) {
  try {
    await refresh($)
  } catch {
    // the status line is a convenience; never let it disturb the session
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    await safeRefresh($)
    $.clock.every(REFRESH_MS, () => void safeRefresh($))
    return started
  })
}
