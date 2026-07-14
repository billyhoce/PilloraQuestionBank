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
    expect(buildPdfFilename({ variant: 'question', title: 'Term 1: A/B "Test"?' })).toBe(
      'Pillora_Term 1 AB Test_Questions.pdf',
    )
  })

  it('falls back to the default cover title when the title is blank', () => {
    expect(buildPdfFilename({ variant: 'combined', title: '' })).toBe('Pillora_Topical Worksheets_Ques and Ans.pdf')
    expect(buildPdfFilename({ variant: 'question', title: '   ' })).toBe('Pillora_Topical Worksheets_Questions.pdf')
    expect(buildPdfFilename({ variant: 'answer' })).toBe('Pillora_Topical Worksheets_Answers.pdf')
  })

  it('defaults an unknown variant to the combined label', () => {
    expect(buildPdfFilename({ variant: 'nope', title: 'Worksheet' })).toBe('Pillora_Worksheet_Ques and Ans.pdf')
  })
})
