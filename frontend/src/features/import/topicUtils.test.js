import { describe, it, expect } from 'vitest'
import {
  emptyPart,
  partsFromApi,
  partsToPayload,
  partsTotalMarks,
  selectionsToAssignments,
} from './topicUtils'

describe('selectionsToAssignments', () => {
  it('groups subtopics under their topic', () => {
    expect(selectionsToAssignments([
      { topic_id: 1, subtopic_id: 11 },
      { topic_id: 1, subtopic_id: 12 },
      { topic_id: 2, subtopic_id: null },
    ])).toEqual([
      { topic_id: 1, subtopics: [{ subtopic_id: 11 }, { subtopic_id: 12 }] },
      { topic_id: 2, subtopics: [] },
    ])
  })
})

describe('partsFromApi', () => {
  it('maps the API shape onto the editor shape', () => {
    expect(partsFromApi([
      { part_order: 0, label: '(a)(i)', marks: 2, selections: [{ topic_id: 3, subtopic_id: 11 }] },
      { part_order: 1, label: '(b)', marks: null, selections: [] },
    ])).toEqual([
      { label: '(a)(i)', marks: 2, selected: [{ topic_id: 3, subtopic_id: 11 }] },
      { label: '(b)', marks: null, selected: [] },
    ])
  })

  it('yields one blank part when there are none', () => {
    expect(partsFromApi([])).toEqual([emptyPart()])
    expect(partsFromApi(undefined)).toEqual([emptyPart()])
  })

  it('defaults a missing label and marks rather than dropping the part', () => {
    expect(partsFromApi([{ selections: [] }])).toEqual([{ label: '', marks: null, selected: [] }])
  })
})

describe('partsToPayload', () => {
  it('emits label, marks and grouped topic assignments per part', () => {
    expect(partsToPayload([
      { label: '(a)', marks: 2, selected: [{ topic_id: 3, subtopic_id: 11 }] },
      { label: '(b)', marks: null, selected: [] },
    ])).toEqual([
      { label: '(a)', marks: 2, topic_assignments: [{ topic_id: 3, subtopics: [{ subtopic_id: 11 }] }] },
      { label: '(b)', marks: null, topic_assignments: [] },
    ])
  })

  it('round-trips through partsFromApi', () => {
    const api = [{ part_order: 0, label: '(a)', marks: 4, selections: [{ topic_id: 1, subtopic_id: null }] }]
    expect(partsToPayload(partsFromApi(api))).toEqual([
      { label: '(a)', marks: 4, topic_assignments: [{ topic_id: 1, subtopics: [] }] },
    ])
  })
})

describe('partsTotalMarks', () => {
  it('sums the marked parts', () => {
    expect(partsTotalMarks([{ marks: 2 }, { marks: 3 }, { marks: 5 }])).toBe(10)
  })

  it('ignores unmarked parts rather than treating them as zero', () => {
    expect(partsTotalMarks([{ marks: 8 }, { marks: null }])).toBe(8)
  })

  it('is null when no part carries marks, matching the backend SUM', () => {
    expect(partsTotalMarks([{ marks: null }, { marks: null }])).toBeNull()
    expect(partsTotalMarks([])).toBeNull()
  })
})
