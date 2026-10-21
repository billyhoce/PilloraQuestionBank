import { describe, expect, it } from 'vitest'
import {
  candidateQuery, coverageNote, detailsText, differences, locationText, needsPartner, pairingState,
} from './pairing'

const REFS = {
  subjects: [{ id: 1, name: 'Math' }], streams: [{ id: 2, name: 'G3' }], levels: [{ id: 3, name: 'Sec 3' }],
  schools: [{ id: 4, name: 'RI' }, { id: 6, name: 'HCI' }], examTypes: [{ id: 5, name: 'EOY' }],
}
const q = (number, answered) => ({ number, question_rects: [{}], answer_rects: answered ? [{}] : [] })

describe('needsPartner', () => {
  it('is an answer-only paper, or a question paper with no answers at all', () => {
    expect(needsPartner({ role: 'answer_only', questions: [q(1, true)] })).toBe(true)
    expect(needsPartner({ questions: [q(1, false), q(2, false)] })).toBe(true)
    expect(needsPartner({ questions: [q(1, true), q(2, false)] })).toBe(false) // partly answered: warned instead
    expect(needsPartner({ questions: [q(1, true)] })).toBe(false)
    expect(needsPartner({ questions: [] })).toBe(false) // nothing to pair; it can only be skipped
  })
})

describe('pairingState', () => {
  it('prefers a link, then a proposed bank paper, else none', () => {
    const paper = { id: 9 }
    expect(pairingState({ link: { paper_key: 'q1' }, proposal: { status: 'proposed', paper } })).toBe('linked')
    expect(pairingState({ link: null, proposal: { status: 'proposed', paper } })).toBe('proposed')
    expect(pairingState({ link: null, proposal: { status: 'manual', paper: null } })).toBe('none')
    expect(pairingState({})).toBe('none')
  })
})

describe('candidateQuery', () => {
  it('drops blank fields, and searches a new school by name', () => {
    expect(candidateQuery({ subject_id: 1, stream_id: null, school_id: 4, new_school_name: null, year: '2024', paper_number: ' ' }))
      .toEqual({ subject_id: 1, school_id: 4, year: 2024 })
    expect(candidateQuery({ school_id: null, new_school_name: 'Raffles Instn', year: '' }))
      .toEqual({ new_school_name: 'Raffles Instn' })
  })
})

describe('differences', () => {
  it('names each differing field with both values', () => {
    const c = { differ: ['school_id', 'paper_number'], details: { school_id: 6, paper_number: '2A' } }
    expect(differences(c, { school_id: 4, paper_number: '2' }, REFS)).toEqual(['school HCI ≠ RI', 'paper no. 2A ≠ 2'])
  })

  it('says a field is missing when the booklet has none', () => {
    const c = { differ: ['year'], details: { year: null } }
    expect(differences(c, { year: '2024' }, REFS)).toEqual(['year — ≠ 2024'])
  })
})

describe('detailsText', () => {
  it('reads the details in words, naming a new school', () => {
    const d = { school_id: 4, year: 2024, level_id: 3, subject_id: 1, exam_type_id: 5, stream_id: 2, paper_number: '1' }
    expect(detailsText(d, REFS)).toBe('RI 2024 Sec 3 Math EOY G3 Paper 1')
    expect(detailsText({ school_id: null, new_school_name: 'Raffles Instn', year: 2023 }, REFS)).toBe('Raffles Instn (new) 2023')
  })
})

describe('locationText', () => {
  it('says where the booklet is', () => {
    expect(locationText({ kind: 'bank', paper_id: 7 })).toBe('In the bank (paper 7)')
    expect(locationText({ kind: 'pending', same_job: true, paper_key: 'q1' })).toBe('Same file (q1)')
    expect(locationText({ kind: 'pending', same_job: false, filename: 'q.pdf', paper_key: 'q1' })).toBe('Pending in q.pdf (q1)')
  })
})

describe('coverageNote', () => {
  it('warns about a partly answered bank paper and marks a fully answered one', () => {
    expect(coverageNote({ kind: 'bank', answer_coverage: 'partial', question_numbers: [1, 2, 3], answer_numbers: [1, 2] }))
      .toBe('Only 2 of 3 questions have answers')
    expect(coverageNote({ kind: 'bank', answer_coverage: 'all', question_numbers: [1], answer_numbers: [1] })).toBe('Already has answers')
    expect(coverageNote({ kind: 'bank', answer_coverage: 'none', question_numbers: [1], answer_numbers: [] })).toBeNull()
    expect(coverageNote({ kind: 'pending', answer_coverage: 'all' })).toBeNull()
  })
})
