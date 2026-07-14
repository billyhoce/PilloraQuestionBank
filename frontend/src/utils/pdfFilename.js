/**
 * Descriptive filenames for generated PDFs.
 *
 * Format: `Pillora_<Title>_<PDFType>.pdf`
 * where <Title> is the worksheet Title (cover title) the user entered and
 * <PDFType> is `Ques and Ans` (combined), `Questions`, or `Answers`.
 *
 * The Title is trimmed and stripped of characters that are invalid in
 * filenames. When the Title is blank, it is omitted entirely, giving a
 * shorter form, e.g. `Pillora_Questions.pdf`.
 */

const PDF_TYPE_LABEL = {
  combined: 'Ques and Ans',
  question: 'Questions',
  answer: 'Answers',
}

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
 * @param {string} [params.title] - the worksheet (cover) title.
 * @returns {string} filename ending in `.pdf`.
 */
export function buildPdfFilename({ variant, title }) {
  const type = PDF_TYPE_LABEL[variant] || 'Ques and Ans'
  const cleanTitle = sanitizeTitle(title)

  if (!cleanTitle) {
    return `Pillora_${type}.pdf`
  }
  return `Pillora_${cleanTitle}_${type}.pdf`
}
