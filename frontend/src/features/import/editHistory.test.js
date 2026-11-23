import { describe, it, expect } from 'vitest'
import { UNDO_LIMIT, breakGesture, emptyHistory, record, redo, undo } from './editHistory'

const p = n => ({ n })

describe('editHistory', () => {
  it('undoes edits newest first, then has nothing left', () => {
    let h = record(record(emptyHistory, p(0)), p(1))
    let r = undo(h, p(2))
    expect(r.paper).toEqual(p(1))
    r = undo(r.history, r.paper)
    expect(r.paper).toEqual(p(0))
    expect(undo(r.history, r.paper)).toBeNull()
  })

  it(`keeps only the last ${UNDO_LIMIT} edits`, () => {
    let h = emptyHistory
    for (let i = 0; i < UNDO_LIMIT + 5; i++) h = record(h, p(i))
    expect(h.past).toHaveLength(UNDO_LIMIT)
    expect(h.past[0]).toEqual(p(5))
  })

  it('records one step for a whole gesture, and a new one after a break', () => {
    const drag = {}
    let h = record(emptyHistory, p(0), drag)
    h = record(h, p(1), drag)
    h = record(h, p(2), drag)
    expect(h.past).toEqual([p(0)])
    h = record(breakGesture(h), p(3), drag)
    expect(h.past).toEqual([p(0), p(3)])
  })

  it('redoes an undone edit until a new edit is made', () => {
    const h = record(emptyHistory, p(0))
    const u = undo(h, p(1))
    const r = redo(u.history, u.paper)
    expect(r.paper).toEqual(p(1))
    expect(r.history.past).toEqual([p(0)])
    const again = undo(r.history, r.paper)
    expect(record(again.history, again.paper).future).toEqual([])
  })
})
