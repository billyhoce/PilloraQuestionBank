import { describe, it, expect } from 'vitest'
import { isPdf, pdfsFromDataTransfer, pdfsFromFileList } from './collectPdfs'

const file = (name, type = 'application/pdf') => new File(['x'], name, { type })

// A FileSystemEntry tree as webkitGetAsEntry returns it; readEntries hands out batches of 2.
const fileEntry = f => ({ isFile: true, isDirectory: false, name: f.name, file: ok => ok(f) })
function dirEntry(name, children) {
  return {
    isFile: false, isDirectory: true, name,
    createReader() {
      let at = 0
      return { readEntries: ok => { const batch = children.slice(at, at + 2); at += 2; ok(batch) } }
    },
  }
}
const item = entry => ({ kind: 'file', webkitGetAsEntry: () => entry })

describe('collectPdfs', () => {
  it('recognises PDFs by type or extension', () => {
    expect(isPdf(file('a.pdf'))).toBe(true)
    expect(isPdf(file('B.PDF', ''))).toBe(true)
    expect(isPdf(file('c.docx', 'application/msword'))).toBe(false)
  })

  it('keeps the PDFs of a picked list in name order and counts the rest', () => {
    const { pdfs, ignored } = pdfsFromFileList([file('p10.pdf'), file('notes.txt', 'text/plain'), file('p2.pdf'), file('._p2.pdf')])
    expect(pdfs.map(f => f.name)).toEqual(['p2.pdf', 'p10.pdf'])
    expect(ignored).toBe(2)
  })

  it('walks dropped folders, nested and read in batches', async () => {
    const dt = {
      items: [
        item(dirEntry('2024', [
          fileEntry(file('b.pdf')), fileEntry(file('a.pdf')), fileEntry(file('readme.md', 'text/markdown')),
          dirEntry('answers', [fileEntry(file('a-ans.pdf'))]),
        ])),
        item(fileEntry(file('loose.pdf'))),
      ],
      files: [],
    }
    const { pdfs, ignored } = await pdfsFromDataTransfer(dt)
    expect(pdfs.map(f => f.name)).toEqual(['a.pdf', 'a-ans.pdf', 'b.pdf', 'loose.pdf'])
    expect(ignored).toBe(1)
  })

  it('falls back to the flat file list without entry support', async () => {
    const { pdfs } = await pdfsFromDataTransfer({ items: [{ kind: 'file' }], files: [file('x.pdf')] })
    expect(pdfs.map(f => f.name)).toEqual(['x.pdf'])
  })
})
