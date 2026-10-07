// Review-page coordinate maths. The proposal's rectangles are PDF points on a booklet page;
// the review image is that page rasterised at some zoom, and the API reports its pixel size
// (width_px / height_px) beside the page's size in points. Nothing here assumes the zoom.

// Pixels per point on a page (horizontal, vertical); both equal the zoom unless rounding differs.
export function pageScale(page) {
  return { sx: page.width_px / page.width_pt, sy: page.height_px / page.height_pt }
}

// A proposal rectangle ({x0,y0,x1,y1} in points) as an SVG <rect> box in the page image's pixels.
export function rectToPx(rect, page) {
  const { sx, sy } = pageScale(page)
  return {
    x: rect.x0 * sx,
    y: rect.y0 * sy,
    width: (rect.x1 - rect.x0) * sx,
    height: (rect.y1 - rect.y0) * sy,
  }
}

// The rectangles of `list` that sit on booklet page `pageNumber`.
export function rectsOnPage(list, pageNumber) {
  return (list || []).filter(r => r.page === pageNumber)
}

// The first booklet page a question touches (its question rectangles, else its answers), or null.
export function firstPageOf(question) {
  const pages = [...(question.question_rects || []), ...(question.answer_rects || [])].map(r => r.page)
  return pages.length ? Math.min(...pages) : null
}
