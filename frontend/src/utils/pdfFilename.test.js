import { describe, it, expect } from 'vitest'
import { buildPdfFilename } from './pdfFilename'

const now = new Date('2026-07-14T09:30:00')

const ctx = {
  level: 'Sec 4',
  stream: 'G3',
  subject: 'E Math',
}

describe('buildPdfFilename', () => {
  it('maps each variant to its PDF type label', () => {
    expect(buildPdfFilename({ variant: 'combined', context: ctx })).toBe('Pillora_Sec4_G3_EMath_Paper.pdf')
    expect(buildPdfFilename({ variant: 'question', context: ctx })).toBe('Pillora_Sec4_G3_EMath_Questions.pdf')
    expect(buildPdfFilename({ variant: 'answer', context: ctx })).toBe('Pillora_Sec4_G3_EMath_Answers.pdf')
  })

  it('strips spaces from level and subject names', () => {
    const context = { level: 'Sec 4', stream: 'G3', subject: 'A Math' }
    expect(buildPdfFilename({ variant: 'combined', context })).toBe('Pillora_Sec4_G3_AMath_Paper.pdf')
  })

  it('includes code and hyphenated name for a single topic', () => {
    const context = { ...ctx, topics: [{ topic_number: 1, name: 'Algebra' }] }
    expect(buildPdfFilename({ variant: 'combined', context })).toBe('Pillora_Sec4_G3_EMath_T1-Algebra_Paper.pdf')
  })

  it('hyphenates spaces and drops invalid characters in a single topic name', () => {
    const context = { ...ctx, topics: [{ topic_number: 18, name: 'Properties of Circles' }] }
    expect(buildPdfFilename({ variant: 'question', context })).toBe(
      'Pillora_Sec4_G3_EMath_T18-Properties-of-Circles_Questions.pdf',
    )
  })

  it('includes codes only for 2–5 topics, sorted ascending', () => {
    const context = {
      ...ctx,
      topics: [
        { topic_number: 28, name: 'Statistics' },
        { topic_number: 1, name: 'Algebra' },
        { topic_number: 23, name: 'Trigonometry' },
      ],
    }
    expect(buildPdfFilename({ variant: 'combined', context })).toBe('Pillora_Sec4_G3_EMath_T1_T23_T28_Paper.pdf')
  })

  it('omits the topic portion when more than 5 topics are selected', () => {
    const topics = Array.from({ length: 6 }, (_, i) => ({ topic_number: i + 1, name: `Topic ${i + 1}` }))
    const context = { ...ctx, topics }
    expect(buildPdfFilename({ variant: 'combined', context })).toBe('Pillora_Sec4_G3_EMath_Paper.pdf')
  })

  it('omits the topic portion when no topic (All) is selected', () => {
    const context = { ...ctx, topics: [] }
    expect(buildPdfFilename({ variant: 'combined', context })).toBe('Pillora_Sec4_G3_EMath_Paper.pdf')
  })

  it('falls back to a dated name when no structured filter is active', () => {
    expect(buildPdfFilename({ variant: 'combined', context: {}, now })).toBe('Pillora_2026-07-14_Paper.pdf')
    expect(buildPdfFilename({ variant: 'question', context: {}, now })).toBe('Pillora_2026-07-14_Questions.pdf')
    expect(buildPdfFilename({ variant: 'answer', context: {}, now })).toBe('Pillora_2026-07-14_Answers.pdf')
  })

  it('builds partial names when only some of level/stream/subject are set', () => {
    expect(buildPdfFilename({ variant: 'combined', context: { level: 'Sec 4' } })).toBe('Pillora_Sec4_Paper.pdf')
  })
})
