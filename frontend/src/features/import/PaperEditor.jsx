import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { clientToPt, firstPageOf, rectToPx } from './reviewGeometry'
import {
  addRect, assignAnswer, changeBetween, deleteRect, drawError, followSelection, getRect, mergeWithPrevious, moveRect, nextNumber, normalise,
  renumber, renumberError, resizeRect, splitBetween, splitThrough,
} from './proposalReducer'
import { isAnswerOnly } from './pairing'
import { breakGesture, emptyHistory, record, redo, undo } from './editHistory'

const HANDLE_PX = 14
const COLOUR = { question: '#2563eb', answer: '#16a34a', orphan: '#6b7280' }

// Keyboard and wheel: an arrow key moves the selected box NUDGE_PT points (Shift: ten times that),
// or with nothing selected turns the page (down/right next, up/left previous).
const NUDGE_PT = 1
const NUDGE = 'nudge'
const ARROWS = {
  ArrowLeft: { dx: -1, dy: 0, page: -1 },
  ArrowRight: { dx: 1, dy: 0, page: 1 },
  ArrowUp: { dx: 0, dy: -1, page: -1 },
  ArrowDown: { dx: 0, dy: 1, page: 1 },
}
// A wheel gesture turns at most one page per this long, so one notch is one page even when the
// device sends a burst of events.
const WHEEL_TURN_MS = 250
const MAX_ZOOM = 5

// Edge handles of the selected rectangle: which coordinate each one drags, and where it sits.
const HANDLES = [
  { edge: 'x0', cursor: 'ew-resize', at: b => ({ x: b.x - HANDLE_PX / 2, y: b.y, width: HANDLE_PX, height: b.height }) },
  { edge: 'x1', cursor: 'ew-resize', at: b => ({ x: b.x + b.width - HANDLE_PX / 2, y: b.y, width: HANDLE_PX, height: b.height }) },
  { edge: 'y0', cursor: 'ns-resize', at: b => ({ x: b.x, y: b.y - HANDLE_PX / 2, width: b.width, height: HANDLE_PX }) },
  { edge: 'y1', cursor: 'ns-resize', at: b => ({ x: b.x, y: b.y + b.height - HANDLE_PX / 2, width: b.width, height: HANDLE_PX }) },
]

const sameSel = (a, b) => a && b && a.list === b.list && a.i === b.i && (a.list === 'orphan' || a.q === b.q)

function Overlay({ page, paper, sel, onSelect, onResize, onMove, onDragStart, onDragEnd, drawKind, onDraw }) {
  const svgRef = useRef(null)
  const drag = useRef(null)
  // The box being drawn, in points: { x0, y0, x1, y1 } (corners in drawing order).
  const [draft, setDraft] = useState(null)
  const boxes = []
  const add = (list, q, rects, label) =>
    rects.forEach((r, i) => {
      if (r.page === page.page) boxes.push({ list, q, i, label, box: rectToPx(r, page), rect: r })
    })
  paper.questions.forEach((q, k) => {
    add('question', k, q.question_rects, `Q${q.number}`)
    add('answer', k, q.answer_rects, `A${q.number}`)
  })
  add('orphan', null, paper.orphan_answers, null)

  const toPt = e => clientToPt(e.clientX, e.clientY, svgRef.current.getBoundingClientRect(), page)

  function move(e) {
    const d = drag.current
    if (!d) return
    const pt = toPt(e)
    if (d.edge) onResize(d.sel, { [d.edge]: d.edge[0] === 'x' ? pt.x : pt.y })
    else onMove(d.sel, d.rect.x0 + pt.x - d.start.x, d.rect.y0 + pt.y - d.start.y)
  }
  // A drag keeps the box's index while it lasts; the box takes its place in order when it ends.
  const endDrag = () => {
    if (drag.current) onDragEnd()
    drag.current = null
  }

  // Drawing: press on the page, drag, release.
  function drawStart(e) {
    if (!drawKind) return
    e.preventDefault()
    e.currentTarget.setPointerCapture?.(e.pointerId)
    const pt = toPt(e)
    setDraft({ x0: pt.x, y0: pt.y, x1: pt.x, y1: pt.y })
  }
  function drawMove(e) {
    if (!draft) return
    const pt = toPt(e)
    setDraft(d => ({ ...d, x1: pt.x, y1: pt.y }))
  }
  function drawEnd() {
    if (!draft) return
    onDraw({ page: page.page, ...draft })
    setDraft(null)
  }

  const draftBox = draft && rectToPx({
    x0: Math.min(draft.x0, draft.x1), x1: Math.max(draft.x0, draft.x1),
    y0: Math.min(draft.y0, draft.y1), y1: Math.max(draft.y0, draft.y1),
  }, page)

  return (
    <svg
      ref={svgRef}
      data-testid="overlay"
      data-drawing={drawKind || undefined}
      viewBox={`0 0 ${page.width_px} ${page.height_px}`}
      className="absolute inset-0 w-full h-full"
      style={{ cursor: drawKind ? 'crosshair' : undefined, touchAction: drawKind ? 'none' : undefined }}
      onClick={() => { if (!drawKind) onSelect(null) }}
      onPointerDown={drawStart}
      onPointerMove={drawMove}
      onPointerUp={drawEnd}
      onPointerCancel={() => setDraft(null)}
    >
      {boxes.map(b => {
        const s = { list: b.list, q: b.q, i: b.i }
        const on = sameSel(sel, s)
        const inQuestion = sel && sel.list !== 'orphan' && b.q === sel.q
        return (
          <g key={`${b.list}-${b.q}-${b.i}`} data-kind={b.list} data-selected={on || undefined}
            pointerEvents={drawKind ? 'none' : undefined}>
            <rect
              {...b.box}
              data-testid={on ? 'selected-rect' : undefined}
              fill={COLOUR[b.list]}
              fillOpacity={on ? 0.3 : inQuestion ? 0.2 : 0.1}
              stroke={COLOUR[b.list]}
              strokeWidth={on || inQuestion ? 2 : 1}
              vectorEffect="non-scaling-stroke"
              strokeDasharray={b.list === 'orphan' ? '8 4' : undefined}
              style={{ cursor: on ? 'move' : 'pointer', touchAction: on ? 'none' : undefined }}
              onClick={e => { e.stopPropagation(); onSelect(s) }}
              onPointerDown={on ? e => {
                // Drag the selected box to move it.
                e.stopPropagation()
                e.currentTarget.setPointerCapture?.(e.pointerId)
                drag.current = { sel: s, rect: b.rect, start: toPt(e) }
                onDragStart()
              } : undefined}
              onPointerMove={on ? move : undefined}
              onPointerUp={on ? endDrag : undefined}
              onPointerCancel={on ? endDrag : undefined}
            />
            {b.label && (
              <text x={b.box.x + 6} y={b.box.y + 22} fontSize="20" fill={COLOUR[b.list]} pointerEvents="none">
                {b.label}
              </text>
            )}
            {on && HANDLES.map(h => (
              <rect
                key={h.edge}
                data-testid={`handle-${h.edge}`}
                {...h.at(b.box)}
                // Invisible: only the grab area along each edge, with its resize cursor.
                fill={COLOUR[b.list]}
                fillOpacity={0}
                style={{ cursor: h.cursor, touchAction: 'none' }}
                onClick={e => e.stopPropagation()}
                onPointerDown={e => {
                  e.stopPropagation()
                  e.currentTarget.setPointerCapture?.(e.pointerId)
                  drag.current = { sel: s, edge: h.edge }
                  onDragStart()
                }}
                onPointerMove={move}
                onPointerUp={endDrag}
                onPointerCancel={endDrag}
              />
            ))}
          </g>
        )
      })}
      {draftBox && (
        <rect data-testid="draft-rect" {...draftBox} fill={COLOUR[drawKind]} fillOpacity={0.15}
          stroke={COLOUR[drawKind]} strokeWidth={2} strokeDasharray="6 3" pointerEvents="none" />
      )}
    </svg>
  )
}

// What the selected box is, in words, and what can be done to it: delete it, and for an answer
// box, give it to another question (or leave it unmatched).
function SelectionPanel({ paper, sel, onDelete, onAssign }) {
  const rect = getRect(paper, sel)
  if (!rect) return null
  const q = sel.list === 'orphan' ? null : paper.questions[sel.q]
  const what = sel.list === 'orphan' ? 'Unmatched answer box'
    : sel.list === 'answer' ? `Answer box of question ${q.number}`
      : `Question box of question ${q.number}`
  const canAssign = sel.list !== 'question' && paper.questions.length > 0
  return (
    <div role="region" aria-label="Selected box" className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs bg-gray-50 border border-gray-200 rounded px-2 py-1.5">
      <span className="font-medium text-gray-700">{what}</span>
      <span className="text-gray-500">page {rect.page} · drag to move, drag an edge to resize</span>
      {canAssign && (
        <label className="flex items-center gap-1 text-gray-700">
          Belongs to
          <select
            aria-label="Assign answer box to question"
            value={sel.list === 'orphan' ? '' : String(sel.q)}
            onChange={e => onAssign(e.target.value === '' ? null : Number(e.target.value))}
            className="border border-gray-300 rounded px-1 py-0.5 text-xs"
          >
            <option value="">No question (not imported)</option>
            {paper.questions.map((o, k) => <option key={k} value={k}>Question {o.number}</option>)}
          </select>
        </label>
      )}
      <button type="button" onClick={onDelete} className="ml-auto text-red-600 hover:underline">Delete box</button>
    </div>
  )
}

// The drawing tools: one press draws one box, for a question number asked for first.
// `prompt` is the open number field ({ kind, text, error }); `drawing` the box being drawn
// ({ kind, number }) once the number is accepted.
function DrawToolbar({ answerOnly, prompt, drawing, onOpen, onText, onStart, onCancel }) {
  const tools = answerOnly ? [['answer', 'Draw answer box']] : [['question', 'Draw question box'], ['answer', 'Draw answer box']]
  const active = prompt?.kind ?? drawing?.kind ?? null
  return (
    <div className="mb-2 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        {tools.map(([kind, label]) => (
          <button
            key={kind}
            type="button"
            aria-pressed={active === kind}
            onClick={() => (active === kind ? onCancel() : onOpen(kind))}
            className={`rounded border px-2 py-1 font-medium ${
              active === kind ? 'bg-blue-600 border-blue-600 text-white' : 'bg-white border-gray-300 text-gray-700 hover:bg-gray-50'
            }`}
          >
            {label}
          </button>
        ))}
        {drawing ? (
          <span role="status" className="text-gray-600">
            Drag on the page to draw {drawing.kind === 'question' ? 'a question' : 'an answer'} box for {answerOnly ? 'answer' : 'question'} {drawing.number}. Esc cancels.
          </span>
        ) : !prompt && (
          <span className="text-gray-500">Click a box to select it, or draw a new box.</span>
        )}
      </div>
      {prompt && (
        <form
          className="mt-1 flex flex-wrap items-center gap-2"
          onSubmit={e => { e.preventDefault(); onStart() }}
        >
          <label className="flex items-center gap-1 text-gray-700">
            {prompt.kind === 'question' ? 'Question box for question' : `Answer box for ${answerOnly ? 'answer' : 'question'}`}
            <input
              type="text"
              inputMode="numeric"
              autoFocus
              aria-label="Question number for the new box"
              aria-invalid={prompt.error ? 'true' : undefined}
              value={prompt.text}
              onChange={e => onText(e.target.value.replace(/\D/g, ''))}
              onKeyDown={e => { if (e.key === 'Escape') onCancel() }}
              className="w-14 border border-gray-300 rounded px-1 text-sm"
            />
          </label>
          <button type="submit" className="rounded border border-blue-600 px-2 py-1 font-medium text-blue-700 hover:bg-blue-50">
            Start drawing
          </button>
          <button type="button" onClick={onCancel} className="text-gray-600 hover:underline">Cancel</button>
          {prompt.error && <span role="alert" className="w-full text-red-600">{prompt.error}</span>}
        </form>
      )}
    </div>
  )
}

// A question's number; committed on blur or Enter, refused (with the reason) if it clashes.
function NumberField({ paper, q, onCommit }) {
  const number = paper.questions[q].number
  const [text, setText] = useState(String(number))
  const [error, setError] = useState(null)
  useEffect(() => { setText(String(number)); setError(null) }, [number])
  function commit() {
    const n = Number(text)
    const err = text.trim() === '' ? 'A question number must be a positive whole number' : renumberError(paper, q, n)
    setError(err)
    if (!err) onCommit(n)
  }
  return (
    <span className="inline-flex flex-col">
      <input
        type="number"
        min="1"
        aria-label={`Number of question ${number}`}
        aria-invalid={error ? 'true' : undefined}
        value={text}
        onChange={e => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={e => { if (e.key === 'Enter') commit() }}
        className="w-14 border border-gray-300 rounded px-1 text-sm"
      />
      {error && <span role="alert" className="text-xs text-red-600">{error}</span>}
    </span>
  )
}

const flaggedPage = p => p.needs_review
const excludedPage = p => Boolean(p.excluded_reason)

// One paper's boxes, editable: the page strip, the page with its boxes and drawing tools, and the
// question list. `onChange(next)` receives each edited paper (the caller stores and saves it); a
// decided paper (`paper.outcome`) is read-only. Remount it (a `key`) to open another paper.
// `renderAnswers(q, k)`, if given, shows under each question where its answers come from (a
// linked answer booklet), instead of its own answer boxes' dot. `focus` ({ page, sel }) opens it on
// a page with a box selected (remount it to jump again). It fills its parent's height, which must
// be definite: the page is scaled to fit it and the side columns scroll. `stripTop` sits above the
// page strip.
export default function PaperEditor({ paper, onChange, renderAnswers = null, focus = null, stripTop = null }) {
  // Drawing a new box (one per press of a tool): the number field first, `prompt`
  // ({ kind, text, error }), then `drawing` ({ kind, number }) once its number is accepted.
  const [prompt, setPrompt] = useState(null)
  const [drawing, setDrawing] = useState(null)
  const [pageNo, setPageNo] = useState(focus?.page ?? null)
  const [sel, setSel] = useState(focus?.sel ?? null)
  const answerOnly = isAnswerOnly(paper)
  const readOnly = Boolean(paper.outcome)

  // Every booklet page is listed; with none chosen the page shown is the first question's, else
  // the paper's own first page.
  const firstPage = firstPageOf(paper.questions[0] ?? {}) ?? paper.pages.find(p => !p.excluded_reason)?.page
  const page = paper.pages.find(p => p.page === (pageNo ?? firstPage)) ?? paper.pages[0] ?? null
  const selectedNumber = sel && sel.list !== 'orphan' ? paper.questions[sel.q]?.number ?? null : null

  function cancelDraw() {
    setPrompt(null)
    setDrawing(null)
  }

  // A drawing tool asks for its question number first: the selected question's, else for a
  // question box the next free number (an answer box has no sensible guess, so none).
  function openDraw(kind) {
    const guess = selectedNumber ?? (kind === 'question' ? nextNumber(paper) : null)
    setDrawing(null)
    setPrompt({ kind, text: guess == null ? '' : String(guess), error: null })
  }

  function startDraw() {
    const number = prompt.text === '' ? null : Number(prompt.text)
    const err = drawError(paper, prompt.kind, number)
    if (err) {
      setPrompt({ ...prompt, error: err })
      return
    }
    setPrompt(null)
    setDrawing({ kind: prompt.kind, number })
  }

  function chooseQuestion(k) {
    select({ list: answerOnly ? 'answer' : 'question', q: k, i: 0 })
    const p = firstPageOf(paper.questions[k])
    if (p != null) setPageNo(p)
  }

  // The last edits, for Ctrl+Z / Ctrl+Y (editHistory.js). Kept while this paper is open: it is
  // lost when the editor is remounted (another paper, or the other booklet of a pair).
  const history = useRef(emptyHistory)

  // Apply a pure edit to the paper and hand it on. `nextSel` is the selection afterwards, or a
  // function of the edited paper giving it (default: cleared, since indexes may have shifted).
  // Edits sharing a `gesture` (one drag, one run of nudges) undo as one step.
  function edit(fn, nextSel = null, gesture = null) {
    const next = fn(paper)
    if (next === paper) return
    if (typeof nextSel === 'function') nextSel = nextSel(next)
    history.current = record(history.current, paper, gesture)
    onChange(next)
    setSel(nextSel)
  }

  // Undo or redo, then show what changed: its page, with the box that came back selected (an edit
  // made on another page is not undone out of sight).
  function step(fn) {
    const r = fn(history.current, paper)
    if (!r) return
    history.current = r.history
    const at = changeBetween(paper, r.paper)
    onChange(r.paper)
    if (at) setPageNo(at.page)
    setSel(at?.sel ?? null)
  }

  // Selecting a box ends a run of nudges: the next one is its own undo step.
  function select(s) {
    history.current = breakGesture(history.current)
    setSel(s)
  }

  // Open page `n`; a selected box left behind on another page is deselected, so the arrow keys
  // never move a box out of sight.
  function goToPage(n) {
    setPageNo(n)
    const r = sel && getRect(paper, sel)
    if (r && r.page !== n) select(null)
  }
  function turnPage(d) {
    const i = paper.pages.findIndex(p => p.page === page?.page)
    const to = paper.pages[i + d]
    if (to) goToPage(to.page)
  }

  // One drag is one gesture: pressing on a box or a handle starts it.
  const dragGesture = useRef(null)
  const onDragStart = () => { dragGesture.current = {} }
  const onResize = (s, edges) => edit(p => resizeRect(p, s, edges), s, dragGesture.current)
  const onMove = (s, x0, y0) => edit(p => moveRect(p, s, x0, y0), s, dragGesture.current)
  const onDragEnd = () => edit(normalise, next => followSelection(paper, next, sel), dragGesture.current)

  // An arrow key moves the selected box NUDGE_PT (Shift: ×10); one run of presses is one gesture.
  function nudge(dx, dy) {
    const r = getRect(paper, sel)
    if (!r) return
    edit(p => {
      const moved = moveRect(p, sel, r.x0 + dx, r.y0 + dy)
      return moved === p ? p : normalise(moved)
    }, next => followSelection(paper, next, sel), NUDGE)
  }
  // The selected box, wherever an edit's re-sort put it.
  const followSel = next => followSelection(paper, next, sel)

  // A drawn box goes to the question whose number was given before drawing; it is selected.
  function onDraw(drawn) {
    const { paper: next, sel: nextSel } = addRect(paper, drawing.kind, drawing.number, drawn)
    setDrawing(null)
    if (next !== paper) edit(() => next, nextSel)
  }

  function onAssign(toQ) {
    const { paper: next, sel: nextSel } = assignAnswer(paper, sel, toQ)
    if (next !== paper) edit(() => next, nextSel)
  }

  useEffect(() => {
    function onKey(e) {
      const t = e.target
      if (t && (['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) || t.isContentEditable)) return
      if (e.key === 'Escape') {
        if (prompt || drawing) cancelDraw()
        else select(null)
        return
      }
      const mod = e.ctrlKey || e.metaKey
      if (mod && !readOnly && (e.key === 'z' || e.key === 'Z' || e.key === 'y')) {
        e.preventDefault()
        step(e.key === 'y' || e.shiftKey ? redo : undo)
        return
      }
      const arrow = ARROWS[e.key]
      if (arrow && !mod && !e.altKey) {
        e.preventDefault()
        if (sel && !readOnly) {
          const d = e.shiftKey ? NUDGE_PT * 10 : NUDGE_PT
          nudge(arrow.dx * d, arrow.dy * d)
        } else {
          turnPage(arrow.page)
        }
        return
      }
      if (e.key !== 'Delete' && e.key !== 'Backspace') return
      if (!sel || readOnly) return
      e.preventDefault()
      edit(p => deleteRect(p, sel))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  // Zoom: 1 fits the whole page in its column; up to MAX_ZOOM. `anchor` keeps the point under the
  // pointer still while zooming (applied once the new size is laid out).
  const [zoom, setZoom] = useState(1)
  const pageColumn = useRef(null)
  const anchor = useRef(null)
  const lastTurn = useRef(0)
  useLayoutEffect(() => {
    const el = pageColumn.current
    const a = anchor.current
    if (!el || !a) return
    anchor.current = null
    el.scrollLeft = a.x * a.ratio - a.cx
    el.scrollTop = a.y * a.ratio - a.cy
  }, [zoom])
  // A new page opens at its top (zoomed in, the column scrolls); its thumbnail is brought into view.
  const strip = useRef(null)
  useEffect(() => {
    if (pageColumn.current) pageColumn.current.scrollTop = 0
    strip.current?.querySelector('[aria-current="page"]')?.scrollIntoView?.({ block: 'nearest' })
  }, [page?.page])

  // The wheel over the page: with Ctrl, zoom; at fit, one page per notch (a burst of wheel events,
  // as from a trackpad, turns at most one page per WHEEL_TURN_MS); zoomed in, it scrolls the page.
  // A native listener, since React's wheel handler is passive and cannot stop the browser's own.
  function handleWheel(e) {
    const el = pageColumn.current
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault()
      const next = Math.min(MAX_ZOOM, Math.max(1, zoom * Math.exp(-e.deltaY * 0.002)))
      if (next === zoom) return
      const box = el.getBoundingClientRect()
      const cx = e.clientX - box.left
      const cy = e.clientY - box.top
      anchor.current = { x: el.scrollLeft + cx, y: el.scrollTop + cy, cx, cy, ratio: next / zoom }
      setZoom(next)
      return
    }
    if (zoom > 1 || e.deltaY === 0) return
    e.preventDefault()
    if (e.timeStamp - lastTurn.current < WHEEL_TURN_MS) return
    lastTurn.current = e.timeStamp
    turnPage(e.deltaY > 0 ? 1 : -1)
  }
  const onWheel = useRef(null)
  useEffect(() => { onWheel.current = handleWheel })
  useEffect(() => {
    const el = pageColumn.current
    if (!el) return undefined
    const listener = e => onWheel.current(e)
    el.addEventListener('wheel', listener, { passive: false })
    return () => el.removeEventListener('wheel', listener)
  }, [])

  return (
    <div className="flex-1 min-w-0 h-full flex gap-3">
      <div className="w-36 shrink-0 h-full flex flex-col gap-2">
        {stripTop && <div className="shrink-0">{stripTop}</div>}
        <nav ref={strip} aria-label="Pages" className="flex-1 min-h-0 space-y-2 overflow-y-auto">
          {paper.pages.map(p => (
            <button
              key={p.page}
              type="button"
              data-flagged={flaggedPage(p) || undefined}
              data-excluded={excludedPage(p) || undefined}
              aria-current={page && p.page === page.page ? 'page' : undefined}
              title={p.excluded_reason || p.review_reason || undefined}
              onClick={() => goToPage(p.page)}
              className={`block w-full border-2 rounded text-xs ${
                page && p.page === page.page ? 'border-blue-600' : flaggedPage(p) ? 'border-amber-400' : 'border-gray-200'
              } ${excludedPage(p) ? 'bg-gray-100 text-gray-400' : ''}`}
            >
              {p.url && <img src={p.url} alt={`Page ${p.page} thumbnail`} className={`w-full ${excludedPage(p) ? 'opacity-40' : ''}`} />}
              <span className="block py-0.5">p{p.page}{flaggedPage(p) ? ' !' : ''}</span>
              {excludedPage(p) && <span className="block pb-0.5 leading-tight">{p.excluded_reason}</span>}
            </button>
          ))}
        </nav>
      </div>

      {/* The page is scaled to fit this column whole, both ways (container query units), times the
          zoom; zoomed in, the column scrolls. */}
      <div
        ref={pageColumn}
        data-testid="page-column"
        className={`flex-1 min-w-0 h-full ${zoom > 1 ? 'overflow-auto' : 'overflow-hidden'}`}
        style={{ containerType: 'size' }}
      >
        {page ? (
          <div
            className="relative mx-auto border border-gray-300 bg-white"
            style={{
              aspectRatio: `${page.width_px} / ${page.height_px}`,
              width: `calc(min(100cqw, 100cqh * ${page.width_px} / ${page.height_px}) * ${zoom})`,
            }}
          >
            {page.url ? (
              <img src={page.url} alt={`Page ${page.page}`} className="absolute inset-0 w-full h-full" />
            ) : (
              <p className="p-4 text-sm text-gray-500">The image for this page is missing.</p>
            )}
            <Overlay
              page={page} paper={paper} sel={sel} onSelect={select} onResize={onResize} onMove={onMove}
              onDragStart={onDragStart} onDragEnd={onDragEnd} drawKind={readOnly ? null : drawing?.kind} onDraw={onDraw}
            />
          </div>
        ) : (
          <p className="text-sm text-gray-500">This paper has no pages.</p>
        )}
      </div>

      {/* Beside the page, so the page can take the window's full height: the tools and notes for
          the page shown, then the question list, which scrolls on its own. */}
      <div className="w-64 shrink-0 h-full flex flex-col">
        {page && (
          <div className="shrink-0">
            {!readOnly && (
              <DrawToolbar
                answerOnly={answerOnly}
                prompt={prompt}
                drawing={drawing}
                onOpen={openDraw}
                onText={text => setPrompt(p => ({ ...p, text, error: null }))}
                onStart={startDraw}
                onCancel={cancelDraw}
              />
            )}
            <p className="mb-2 text-xs text-gray-500">
              {sel && !readOnly ? 'Arrow keys move the box (Shift: further). ' : 'Arrow keys or the wheel turn pages. '}
              Ctrl+wheel zooms.{readOnly ? '' : ' Ctrl+Z undoes, Ctrl+Y redoes.'}
              {zoom > 1 && (
                <>
                  {' '}<span className="text-gray-700">{Math.round(zoom * 100)}%</span>{' '}
                  <button type="button" onClick={() => setZoom(1)} className="text-blue-700 hover:underline">Fit page</button>
                </>
              )}
            </p>
            {!readOnly && sel && !prompt && !drawing && (
              <SelectionPanel paper={paper} sel={sel} onDelete={() => edit(p => deleteRect(p, sel))} onAssign={onAssign} />
            )}
            {excludedPage(page) && (
              <p className="mb-2 text-xs text-gray-700 bg-gray-100 border border-gray-300 rounded px-2 py-1">
                Not used by the pipeline: {page.excluded_reason}. Draw boxes here if it holds questions.
              </p>
            )}
            {flaggedPage(page) && (
              <p className="mb-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                Page {page.page} needs review{page.review_reason ? `: ${page.review_reason}` : ''}
              </p>
            )}
          </div>
        )}
        <aside aria-label="Questions" className="flex-1 min-h-0 overflow-y-auto">
          {paper.warnings?.map((w, i) => (
            <p key={i} className="mb-2 text-xs text-amber-800">{w}</p>
          ))}
          {paper.questions.length === 0 ? (
            <p className="text-sm text-gray-500">No questions were found for this paper.</p>
          ) : (
            <ul className="space-y-1">
              {paper.questions.map((q, k) => {
                const active = sel != null && sel.list !== 'orphan' && sel.q === k
                const onQuestionRect = active && sel.list === 'question'
                const rect = onQuestionRect ? getRect(paper, sel) : null
                const ownDot = !answerOnly && !renderAnswers
                return (
                  <li key={q.number} className={`rounded border px-2 py-1 ${
                    active ? 'border-blue-600 bg-blue-50' : q.flags.length ? 'border-amber-300 bg-amber-50' : 'border-gray-200'
                  }`}>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        data-flagged={q.flags.length > 0 || undefined}
                        aria-pressed={active}
                        onClick={() => chooseQuestion(k)}
                        className="flex-1 text-left text-sm"
                      >
                        <span className="font-medium">{answerOnly ? 'Answer' : 'Question'} {q.number}</span>
                        {ownDot && q.answer_rects.length > 0 && (
                          <span
                            role="img" aria-label="has an answer" title="Has an answer"
                            className="ml-1.5 inline-block h-2 w-2 rounded-full bg-green-600 align-middle"
                          />
                        )}
                        {answerOnly && (
                          <span className="text-xs text-gray-500">
                            {' '}({q.answer_rects.length} rectangle{q.answer_rects.length === 1 ? '' : 's'})
                          </span>
                        )}
                        {ownDot && q.answer_rects.length === 0 && (
                          <span className="block text-xs text-amber-800">No answer</span>
                        )}
                        {q.flags.map(f => (
                          <span key={f} className="block text-xs text-amber-800">{f}</span>
                        ))}
                      </button>
                      <NumberField paper={paper} q={k} onCommit={n => edit(p => renumber(p, k, n), followSel)} />
                    </div>
                    {renderAnswers && renderAnswers(q, k)}
                    {active && !readOnly && (
                      <div className="mt-1 flex flex-wrap gap-1 text-xs">
                        {k > 0 && (
                          <button type="button" className="text-blue-700 hover:underline"
                            onClick={() => edit(p => mergeWithPrevious(p, k))}>
                            Merge with previous
                          </button>
                        )}
                        {rect && sel.i > 0 && (
                          <button type="button" className="text-blue-700 hover:underline"
                            onClick={() => edit(p => splitBetween(p, k, sel.i))}>
                            Split before selected rectangle
                          </button>
                        )}
                        {rect && (
                          <button type="button" className="text-blue-700 hover:underline"
                            onClick={() => edit(p => splitThrough(p, k, sel.i, (rect.y0 + rect.y1) / 2))}>
                            Split selected rectangle in half
                          </button>
                        )}
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
          {paper.orphan_answers.length > 0 && (
            <p className="mt-2 text-xs text-gray-600">
              {paper.orphan_answers.length} answer rectangle{paper.orphan_answers.length === 1 ? '' : 's'} not matched to a question (grey, dashed).
              They are not imported.
            </p>
          )}
        </aside>
      </div>
    </div>
  )
}
