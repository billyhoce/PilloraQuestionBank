/**
 * Descriptive filenames for generated PDFs.
 *
 * Format: `Pillora_<Title>_<PDFType>.pdf`
 * where <Title> is the worksheet Title (cover title) the user entered and
 * <PDFType> is `Ques and Ans` (combined), `Questions`, or `Answers`.
 *
 * The Title is trimmed and stripped of characters that are invalid in
 * filenames. The filename always includes a Title: when the field is blank
 * (or not yet loaded), it falls back to the default cover title the backend
 * stamps on the page, so the filename matches the cover.
 */

const PDF_TYPE_LABEL = {
  combined: 'Ques and Ans',
  question: 'Questions',
  answer: 'Answers',
}

// Mirrors DEFAULT_COVER_TITLE in app/schemas/generate.py — the title the
// backend puts on the cover when none is supplied.
const DEFAULT_TITLE = 'Topical Worksheets'

// Drop characters that are invalid in filenames and trim surrounding space.
function sanitizeTitle(value) {
  return String(value ?? '')
    .replace(/[\\/:*?"<>|]/g, '')
    .trim()
}

/**
 * Build a download filename for a generated PDF from the worksheet Title.
 *
 * @param {Object} params
 * @param {'combined'|'question'|'answer'} params.variant - which PDF this is.
 * @param {string} [params.title] - the worksheet (cover) title. Falls back to
 *   the default cover title when blank so a Title is always present.
 * @returns {string} filename ending in `.pdf`.
 */
export function buildPdfFilename({ variant, title }) {
  const type = PDF_TYPE_LABEL[variant] || 'Ques and Ans'
  const cleanTitle = sanitizeTitle(title) || DEFAULT_TITLE

  return `Pillora_${cleanTitle}_${type}.pdf`
}
