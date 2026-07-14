/**
 * Descriptive filenames for generated PDFs, based on the worksheet Title.
 *
 * Format: `Pillora_<Title>_<PDFType>.pdf`
 * where <PDFType> is `Ques and Ans` (combined), `Questions`, or `Answers`.
 *
 * The Title is trimmed and stripped of filename-invalid characters. When it is
 * blank, the Title section is omitted entirely, e.g. `Pillora_Questions.pdf`.
 */

const PDF_TYPE_LABEL = {
  combined: 'Ques and Ans',
  question: 'Questions',
  answer: 'Answers',
}

// Drop characters that are invalid in filenames, then trim surrounding space.
function sanitizeTitle(title) {
  return String(title ?? '')
    .replace(/[\\/:*?"<>|]/g, '')
    .trim()
}

/**
 * Build a download filename for a generated PDF.
 *
 * @param {Object} params
 * @param {'combined'|'question'|'answer'} params.variant - which PDF this is.
 * @param {string} [params.title] - the worksheet Title entered by the user.
 * @returns {string} filename ending in `.pdf`.
 */
export function buildPdfFilename({ variant, title }) {
  const type = PDF_TYPE_LABEL[variant] || 'Ques and Ans'
  const clean = sanitizeTitle(title)
  return clean ? `Pillora_${clean}_${type}.pdf` : `Pillora_${type}.pdf`
}
