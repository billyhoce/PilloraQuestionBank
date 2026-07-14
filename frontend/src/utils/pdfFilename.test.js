import { describe, it, expect } from 'vitest'
import { buildPdfFilename } from './pdfFilename'

describe('buildPdfFilename', () => {
  it('maps each variant to its PDF type label', () => {
    const title = 'Topical Worksheet'
    expect(buildPdfFilename({ variant: 'combined', title })).toBe('Pillora_Topical Worksheet_Ques and Ans.pdf')
    expect(buildPdfFilename({ variant: 'question', title })).toBe('Pillora_Topical Worksheet_Questions.pdf')
    expect(buildPdfFilename({ variant: 'answer', title })).toBe('Pillora_Topical Worksheet_Answers.pdf')
  })

  it('trims leading and trailing spaces from the title', () => {
    expect(buildPdfFilename({ variant: 'combined', title: '  Topical Worksheet  ' })).toBe(
      'Pillora_Topical Worksheet_Ques and Ans.pdf',
    )
  })

  it('removes characters that are invalid in filenames', () => {
    expect(buildPdfFilename({ variant: 'question', title: 'Algebra: Part 1/2 <draft>' })).toBe(
      'Pillora_Algebra Part 12 draft_Questions.pdf',
    )
  })

  it('omits the title section when the title is blank', () => {
    expect(buildPdfFilename({ variant: 'combined', title: '' })).toBe('Pillora_Ques and Ans.pdf')
    expect(buildPdfFilename({ variant: 'question', title: '   ' })).toBe('Pillora_Questions.pdf')
    expect(buildPdfFilename({ variant: 'answer', title: null })).toBe('Pillora_Answers.pdf')
  })

  it('falls back to the combined label for an unknown variant', () => {
    expect(buildPdfFilename({ variant: 'other', title: 'X' })).toBe('Pillora_X_Ques and Ans.pdf')
  })
})
