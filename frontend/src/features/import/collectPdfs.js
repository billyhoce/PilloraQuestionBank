// Gather the PDFs out of what the admin dropped or picked: loose files, whole folders (walked
// recursively), or a folder chosen with the directory picker. Anything that is not a PDF is
// counted, not returned, so the UI can say "3 non-PDF files ignored".

export function isPdf(file) {
  return file.type === 'application/pdf' || /\.pdf$/i.test(file.name || '')
}

// Sort by the path inside the dropped folder when there is one, so a folder of papers queues in
// the order the admin sees it in their file manager.
const pathOf = f => f.webkitRelativePath || f.name || ''

function split(files) {
  const pdfs = files.filter(isPdf).sort((a, b) => pathOf(a).localeCompare(pathOf(b), undefined, { numeric: true }))
  // macOS litters folders with ._foo.pdf resource forks; they are not PDFs whatever they are named.
  const real = pdfs.filter(f => !(f.name || '').startsWith('._'))
  return { pdfs: real, ignored: files.length - real.length }
}

// A FileList (or array) from an <input type="file">, with or without `webkitdirectory`.
export function pdfsFromFileList(fileList) {
  return split(Array.from(fileList || []))
}

// Every entry of a directory. readEntries hands them out in batches until it returns none.
function readAll(reader) {
  return new Promise((resolve, reject) => {
    const out = []
    const next = () => reader.readEntries(batch => {
      if (!batch.length) resolve(out)
      else { out.push(...batch); next() }
    }, reject)
    next()
  })
}

async function walk(entry, path) {
  if (entry.isFile) {
    const file = await new Promise((resolve, reject) => entry.file(resolve, reject))
    // Keep the folder path for ordering; a File's own webkitRelativePath is read-only and empty here.
    if (path && !file.webkitRelativePath) {
      try { Object.defineProperty(file, 'webkitRelativePath', { value: `${path}${file.name}` }) } catch { /* ordering only */ }
    }
    return [file]
  }
  if (entry.isDirectory) {
    const children = await readAll(entry.createReader())
    const nested = await Promise.all(children.map(c => walk(c, `${path}${entry.name}/`)))
    return nested.flat()
  }
  return []
}

// A drop's DataTransfer. Folders are only reachable through `items` + webkitGetAsEntry (read
// synchronously, before any await: the list is emptied once the event handler yields); browsers
// without it fall back to the flat `files`, which holds no folder contents.
export async function pdfsFromDataTransfer(dt) {
  const items = Array.from(dt?.items || [])
  const entries = items
    .filter(it => it.kind === 'file')
    .map(it => (typeof it.webkitGetAsEntry === 'function' ? it.webkitGetAsEntry() : null))
  if (entries.length && entries.every(Boolean)) {
    const files = (await Promise.all(entries.map(e => walk(e, '')))).flat()
    return split(files)
  }
  return pdfsFromFileList(dt?.files)
}
