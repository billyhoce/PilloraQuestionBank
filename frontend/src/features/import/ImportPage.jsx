import { useEffect, useRef, useState } from 'react'
import { api } from '../../api/client'
import UploadDropZone from './UploadDropZone'
import PageGrid from './PageGrid'
import MetadataSidebar from './MetadataSidebar'
import ConfirmSummary from './ConfirmSummary'
import TopicReview from './TopicReview'

const STORAGE_KEY = 'pillora_import_session'

function loadSession() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function saveSession(data) {
  try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data)) } catch {}
}

function clearSession() {
  sessionStorage.removeItem(STORAGE_KEY)
}

function computeQuestions(pages, dividerIdx, marksMap) {
  const qPages = dividerIdx !== null ? pages.slice(0, dividerIdx) : pages
  const aPages = dividerIdx !== null ? pages.slice(dividerIdx) : []

  function group(arr) {
    return arr.reduce((groups, p, i) => {
      if (i === 0 || !p.mergeWithPrev) groups.push([])
      groups[groups.length - 1].push(p)
      return groups
    }, [])
  }

  const qGroups = group(qPages)
  const aGroups = group(aPages)
  const total = Math.max(qGroups.length, aGroups.length)

  return Array.from({ length: total }, (_, i) => {
    const qNum = i + 1
    const pageDatas = [
      ...(qGroups[i] || []).map((p, j) => ({
        temp_key: p.temp_key, page_type: 'question', page_order: j + 1,
        width_px: p.dimensions.width, height_px: p.dimensions.height,
      })),
      ...(aGroups[i] || []).map((p, j) => ({
        temp_key: p.temp_key, page_type: 'answer', page_order: j + 1,
        width_px: p.dimensions.width, height_px: p.dimensions.height,
      })),
    ]
    return { question_number: qNum, marks: marksMap[qNum] ?? null, pages: pageDatas }
  })
}

function countGroups(arr) {
  return arr.reduce((count, p, i) => (i === 0 || !p.mergeWithPrev ? count + 1 : count), 0)
}

const emptyMetadata = {
  subject_id: null, stream_id: null, level_id: null,
  school_id: null, exam_type_id: null, year: '', paper_number: '',
}

export default function ImportPage() {
  const [step, setStep] = useState(() => loadSession()?.step ?? 'upload')
  const [pages, setPages] = useState(() => loadSession()?.pages ?? [])
  const [dividerIdx, setDividerIdx] = useState(() => loadSession()?.dividerIdx ?? null)
  const [metadata, setMetadata] = useState(() => loadSession()?.metadata ?? emptyMetadata)
  const [marksMap, setMarksMap] = useState(() => loadSession()?.marksMap ?? {})
  const [paperId, setPaperId] = useState(() => loadSession()?.paperId ?? null)
  const [confirmedQuestions, setConfirmedQuestions] = useState(() => loadSession()?.confirmedQuestions ?? [])
  const [refs, setRefs] = useState(null)

  const appendInputRef = useRef(null)

  const [uploadLoading, setUploadLoading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState('')
  const [uploadError, setUploadError] = useState(null)
  const [appendLoading, setAppendLoading] = useState(false)
  const [appendError, setAppendError] = useState(null)
  const [confirmLoading, setConfirmLoading] = useState(false)
  const [confirmError, setConfirmError] = useState(null)

  useEffect(() => {
    if (step === 'upload') {
      clearSession()
    } else {
      saveSession({ step, pages, dividerIdx, metadata, marksMap, paperId, confirmedQuestions })
    }
  }, [step, pages, dividerIdx, metadata, marksMap, paperId, confirmedQuestions])

  useEffect(() => {
    Promise.all([
      api.subjects.list(),
      api.streams.list(),
      api.levels.list(),
      api.schools.list(),
      api.examTypes.list(),
      api.schoolLevels.list(),
    ]).then(([subjects, streams, levels, schools, examTypes, schoolLevels]) => {
      const slMap = Object.fromEntries(schoolLevels.map(sl => [sl.id, sl.name]))
      const namedLevels = levels.map(l => ({
        ...l,
        name: slMap[l.school_level_id] ? `${slMap[l.school_level_id]} ${l.name}` : l.name,
      }))
      setRefs({ subjects, streams, levels: namedLevels, schools, examTypes })
    })
  }, [])

  async function handleUpload(files) {
    setUploadLoading(true)
    setUploadError(null)
    try {
      let allPages = []
      let firstMeta = null
      for (let i = 0; i < files.length; i++) {
        setUploadProgress(files.length > 1 ? `Uploading PDF ${i + 1} of ${files.length}…` : 'Converting PDF pages…')
        const result = await api.import.uploadPdf(files[i])
        allPages = [...allPages, ...result.pages.map((p) => ({ ...p, mergeWithPrev: false }))]
        if (firstMeta === null && result.suggested_metadata) firstMeta = result.suggested_metadata
      }
      setPages(allPages)
      setDividerIdx(null)
      if (firstMeta) {
        const s = firstMeta
        setMetadata((prev) => ({
          ...prev,
          ...(s.subject_id != null && { subject_id: s.subject_id }),
          ...(s.stream_id != null && { stream_id: s.stream_id }),
          ...(s.level_id != null && { level_id: s.level_id }),
          ...(s.school_id != null && { school_id: s.school_id }),
          ...(s.exam_type_id != null && { exam_type_id: s.exam_type_id }),
          ...(s.year != null && { year: String(s.year) }),
          ...(s.paper_number != null && { paper_number: String(s.paper_number) }),
        }))
      }
      setStep('review')
    } catch (e) {
      setUploadError(e.message)
    } finally {
      setUploadLoading(false)
      setUploadProgress('')
    }
  }

  async function handleAppend(files) {
    setAppendLoading(true)
    setAppendError(null)
    try {
      for (const file of files) {
        const result = await api.import.uploadPdf(file)
        const newPages = result.pages.map((p) => ({ ...p, mergeWithPrev: false }))
        setPages((prev) => [...prev, ...newPages])
      }
    } catch (e) {
      setAppendError(e.message)
    } finally {
      setAppendLoading(false)
    }
  }

  function handleToggleMerge(idx) {
    setPages((prev) => prev.map((p, i) => (i === idx ? { ...p, mergeWithPrev: !p.mergeWithPrev } : p)))
  }

  function handleSetDivider(idx) {
    setDividerIdx(idx)
    setPages((prev) => prev.map((p, i) => (i === idx ? { ...p, mergeWithPrev: false } : p)))
  }

  async function handleConfirm() {
    setConfirmLoading(true)
    setConfirmError(null)
    try {
      const questions = computeQuestions(pages, dividerIdx, marksMap)
      const result = await api.import.confirm({
        subject_id: metadata.subject_id,
        stream_id: metadata.stream_id,
        level_id: metadata.level_id,
        school_id: metadata.school_id,
        exam_type_id: metadata.exam_type_id,
        year: Number(metadata.year),
        paper_number: metadata.paper_number,
        questions,
      })
      setPaperId(result.paper_id)
      setConfirmedQuestions(result.questions || [])
      setStep('ai_topics')
    } catch (e) {
      setConfirmError(e.message)
    } finally {
      setConfirmLoading(false)
    }
  }

  function resetImport() {
    clearSession()
    setStep('upload')
    setPages([])
    setDividerIdx(null)
    setMetadata(emptyMetadata)
    setMarksMap({})
    setPaperId(null)
    setConfirmedQuestions([])
  }

  function handleDone() { resetImport() }

  function handleCancel() {
    if (window.confirm('Cancel this import? All progress will be lost.')) resetImport()
  }

  async function handleCancelTopicReview() {
    if (!window.confirm('Cancel this import? The paper and all uploaded pages will be deleted.')) return
    try {
      if (paperId != null) await api.import.deletePaper(paperId)
    } catch (e) {
      // best-effort; reset regardless so the user isn't stuck
    }
    resetImport()
  }

  if (step === 'upload') {
    return <UploadDropZone onUpload={handleUpload} loading={uploadLoading} error={uploadError} loadingMessage={uploadProgress} />
  }

  if (step === 'review') {
    const qPages = dividerIdx !== null ? pages.slice(0, dividerIdx) : pages
    const aPages = dividerIdx !== null ? pages.slice(dividerIdx) : []
    return (
      <div className="flex items-start gap-0">
        <div className="flex-1 min-w-0">
          <div className="px-4 pt-3 pb-0 flex items-center gap-3">
            <button
              type="button"
              onClick={() => appendInputRef.current?.click()}
              disabled={appendLoading}
              className="text-sm px-3 py-1 rounded border border-gray-300 hover:border-blue-400 disabled:opacity-50"
            >
              {appendLoading ? 'Appending…' : '+ Append PDF'}
            </button>
            <input
              ref={appendInputRef}
              type="file"
              accept=".pdf,application/pdf"
              multiple
              className="hidden"
              onChange={(e) => { handleAppend(Array.from(e.target.files)); e.target.value = '' }}
            />
            {appendError && <span className="text-red-500 text-sm">{appendError}</span>}
          </div>
          <PageGrid
            pages={pages}
            dividerIdx={dividerIdx}
            onToggleMerge={handleToggleMerge}
            onSetDivider={handleSetDivider}
            onRemoveDivider={() => setDividerIdx(null)}
          />
        </div>
        <MetadataSidebar
          metadata={metadata}
          onChange={setMetadata}
          refs={refs}
          questionCount={countGroups(qPages)}
          answerCount={countGroups(aPages)}
          onNext={() => setStep('confirm_summary')}
          onCancel={handleCancel}
        />
      </div>
    )
  }

  if (step === 'confirm_summary') {
    return (
      <ConfirmSummary
        questions={computeQuestions(pages, dividerIdx, marksMap)}
        metadata={metadata}
        refs={refs}
        marksMap={marksMap}
        onMarksChange={(qNum, val) => setMarksMap((prev) => ({ ...prev, [qNum]: val }))}
        onConfirm={handleConfirm}
        onBack={() => setStep('review')}
        onCancel={handleCancel}
        loading={confirmLoading}
        error={confirmError}
      />
    )
  }

  if (step === 'ai_topics') {
    return (
      <TopicReview
        paperId={paperId}
        questions={confirmedQuestions}
        subjectId={metadata.subject_id}
        streamId={metadata.stream_id}
        onDone={handleDone}
        onCancel={handleCancelTopicReview}
      />
    )
  }

  return null
}
