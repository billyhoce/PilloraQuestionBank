import { describe, it, expect } from 'vitest'
import { pageScale, rectToPx, rectsOnPage, firstPageOf } from './reviewGeometry'

const page = { page: 7, width_pt: 595.3, height_pt: 841.9, width_px: 1191, height_px: 1684 }

describe('review geometry', () => {
  it('scale is image pixels over points, per axis', () => {
    const { sx, sy } = pageScale(page)
    expect(sx).toBeCloseTo(1191 / 595.3)
    expect(sy).toBeCloseTo(1684 / 841.9)
  })

  it('maps a point rectangle to a pixel box', () => {
    const p = { width_pt: 100, height_pt: 200, width_px: 200, height_px: 400 }
    expect(rectToPx({ x0: 10, y0: 20, x1: 60, y1: 120 }, p)).toEqual({ x: 20, y: 40, width: 100, height: 200 })
  })

  it('does not assume a zoom of 2', () => {
    const p = { width_pt: 100, height_pt: 100, width_px: 300, height_px: 300 }
    expect(rectToPx({ x0: 1, y0: 1, x1: 2, y1: 3 }, p)).toEqual({ x: 3, y: 3, width: 3, height: 6 })
  })

  it('a rectangle spanning the whole page maps to the whole image', () => {
    const box = rectToPx({ x0: 0, y0: 0, x1: page.width_pt, y1: page.height_pt }, page)
    expect(box.width).toBeCloseTo(page.width_px)
    expect(box.height).toBeCloseTo(page.height_px)
  })

  it('filters rectangles by page and finds a question\'s first page', () => {
    const q = { question_rects: [{ page: 8 }, { page: 7 }], answer_rects: [{ page: 20 }] }
    expect(rectsOnPage(q.question_rects, 7)).toEqual([{ page: 7 }])
    expect(rectsOnPage(undefined, 7)).toEqual([])
    expect(firstPageOf(q)).toBe(7)
    expect(firstPageOf({ question_rects: [], answer_rects: [{ page: 20 }] })).toBe(20)
    expect(firstPageOf({ question_rects: [], answer_rects: [] })).toBeNull()
  })
})
