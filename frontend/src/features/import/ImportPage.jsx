import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import UploadDropZone from './UploadDropZone'
import PageGrid from './PageGrid'
import MetadataSidebar from './MetadataSidebar'
import ConfirmSummary from './ConfirmSummary'
import TopicReview from './TopicReview'

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
  const [step, setStep] = useState('upload')
  const [pages, setPages] = useState([])
  const [dividerIdx, setDividerIdx] = useState(null)
  const [metadata, setMetadata] = useState(emptyMetadata)
  const [marksMap, setMarksMap] = useState({})
  const [paperId, setPaperId] = useState(null)
  const [refs, setRefs] = useState(null)

  const [uploadLoading, setUploadLoading] = useState(false)
  const [uploadError, setUploadError] = useState(null)
  const [confirmLoading, setConfirmLoading] = useState(false)
  const [confirmError, setConfirmError] = useState(null)

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

  async function handleUpload(file) {
    setUploadLoading(true)
    setUploadError(null)
    try {
      const result = await api.import.uploadPdf(file)
      setPages(result.pages.map((p) => ({ ...p, mergeWithPrev: false })))
      setDividerIdx(null)
      if (result.suggested_metadata) {
        const s = result.suggested_metadata
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
      setStep('ai_topics')
    } catch (e) {
      setConfirmError(e.message)
    } finally {
      setConfirmLoading(false)
    }
  }

  function handleDone() {
    setStep('upload')
    setPages([])
    setDividerIdx(null)
    setMetadata(emptyMetadata)
    setMarksMap({})
    setPaperId(null)
  }

  if (step === 'upload') {
    return <UploadDropZone onUpload={handleUpload} loading={uploadLoading} error={uploadError} />
  }

  if (step === 'review') {
    const qPages = dividerIdx !== null ? pages.slice(0, dividerIdx) : pages
    const aPages = dividerIdx !== null ? pages.slice(dividerIdx) : []
    return (
      <div className="flex items-start gap-0">
        <div className="flex-1 min-w-0">
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
        loading={confirmLoading}
        error={confirmError}
      />
    )
  }

  if (step === 'ai_topics') {
    return <TopicReview paperId={paperId} onDone={handleDone} />
  }

  return null
}
