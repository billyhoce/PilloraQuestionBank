import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import TopicMultiSelect from './TopicMultiSelect'
import TagCombobox from '../TagCombobox'

function Chip({ active, disabled, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`px-3 py-1 text-sm rounded-full border transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
        active
          ? 'bg-blue-600 text-white border-blue-600'
          : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-100'
      }`}
    >
      {children}
    </button>
  )
}

function Row({ label, children }) {
  return (
    <div className="flex items-start gap-4 py-2">
      <div className="w-20 shrink-0 text-xs uppercase tracking-wide text-gray-500 pt-1.5">{label}</div>
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  )
}

export default function FilterBar({ filters, onFilterChange }) {
  const [levels, setLevels] = useState([])
  const [streams, setStreams] = useState([])
  const [subjects, setSubjects] = useState([])
  const [schools, setSchools] = useState([])
  const [examTypes, setExamTypes] = useState([])
  const [schoolLevels, setSchoolLevels] = useState([])
  const [topics, setTopics] = useState([])
  const [tags, setTags] = useState([])
  const [years, setYears] = useState([])
  const [kwInput, setKwInput] = useState(filters.search || '')

  useEffect(() => {
    Promise.all([
      api.levels.list(),
      api.streams.list(),
      api.subjects.list(),
      api.schools.list(),
      api.examTypes.list(),
      api.schoolLevels.list(),
      api.tags.list(),
    ]).then(([lv, st, su, sc, et, sl, tg]) => {
      setLevels(lv || [])
      setStreams(st || [])
      setSubjects(su || [])
      setSchools(sc || [])
      setExamTypes(et || [])
      setSchoolLevels(sl || [])
      setTags(tg || [])
    }).catch(() => {})
  }, [])

  const schoolLevelById = useMemo(() => {
    const map = {}
    for (const sl of schoolLevels) map[sl.id] = sl.name
    return map
  }, [schoolLevels])

  function levelLabel(level) {
    const slName = schoolLevelById[level.school_level_id]
    return slName ? `${slName} ${level.name}` : level.name
  }

  useEffect(() => {
    if (filters.subject_id && filters.stream_id) {
      api.topics.list(filters.subject_id, filters.stream_id)
        .then(data => setTopics(data || []))
        .catch(() => setTopics([]))
    } else {
      setTopics([])
    }
  }, [filters.subject_id, filters.stream_id])

  useEffect(() => {
    api.papers.years({
      subject_id: filters.subject_id,
      stream_id: filters.stream_id,
      level_id: filters.level_id,
    })
      .then(data => setYears(data || []))
      .catch(() => setYears([]))
  }, [filters.subject_id, filters.stream_id, filters.level_id])

  useEffect(() => {
    setKwInput(filters.search || '')
  }, [filters.search])

  // Debounced live search: commit the typed keyword ~300ms after the last
  // keystroke. The no-op guard against the committed filter value prevents a
  // feedback loop with the resync effect above (and avoids re-firing when the
  // input was set programmatically). Enter / the Search button still commit
  // instantly via submitKw().
  useEffect(() => {
    const next = kwInput.trim()
    if (next === (filters.search || '')) return
    const t = setTimeout(() => onFilterChange({ search: next }), 300)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kwInput])

  const selectedLevel = levels.find(l => String(l.id) === String(filters.level_id))
  const selectedStream = streams.find(s => String(s.id) === String(filters.stream_id))

  function pickLevel(level) {
    const patch = { level_id: level.id }
    if (selectedStream && selectedStream.school_level_id !== level.school_level_id) {
      patch.stream_id = ''
    }
    onFilterChange(patch)
  }

  function pickStream(stream) {
    const patch = { stream_id: stream.id }
    if (selectedLevel && selectedLevel.school_level_id !== stream.school_level_id) {
      patch.level_id = ''
    }
    if (stream.id !== filters.stream_id) {
      patch.topic_ids = []
      patch.exclusive = false
    }
    onFilterChange(patch)
  }

  function pickSubject(subject) {
    const patch = { subject_id: subject.id }
    if (subject.id !== filters.subject_id) {
      patch.topic_ids = []
      patch.exclusive = false
    }
    onFilterChange(patch)
  }

  function submitKw() {
    onFilterChange({ search: kwInput.trim() })
  }

  const visibleStreams = selectedLevel
    ? streams.filter(s => s.school_level_id === selectedLevel.school_level_id)
    : streams

  const selectedTagIds = filters.tag_ids || []
  const selectedTags = tags.filter(t => selectedTagIds.includes(t.id))

  function addTag(tag) {
    if (selectedTagIds.includes(tag.id)) return
    onFilterChange({ tag_ids: [...selectedTagIds, tag.id] })
  }
  function removeTag(id) {
    onFilterChange({ tag_ids: selectedTagIds.filter(t => t !== id) })
  }

  return (
    <div className="bg-gray-50 border-2 border-gray-300 rounded-lg p-4 space-y-1">
      <Row label="Level">
        <div className="flex items-center flex-wrap gap-2">
          <Chip active={!filters.level_id} onClick={() => onFilterChange({ level_id: '' })}>All</Chip>
          {levels.map(l => (
            <Chip
              key={l.id}
              active={String(filters.level_id) === String(l.id)}
              onClick={() => pickLevel(l)}
            >
              {levelLabel(l)}
            </Chip>
          ))}
        </div>
      </Row>

      <Row label="Stream">
        <div className="flex items-center flex-wrap gap-2">
          <Chip active={!filters.stream_id} onClick={() => onFilterChange({ stream_id: '', topic_ids: [], exclusive: false })}>All</Chip>
          {visibleStreams.map(s => (
            <Chip
              key={s.id}
              active={String(filters.stream_id) === String(s.id)}
              onClick={() => pickStream(s)}
            >
              {s.name}
            </Chip>
          ))}
        </div>
      </Row>

      <Row label="Subject">
        <div className="flex items-center flex-wrap gap-2">
          <Chip active={!filters.subject_id} onClick={() => onFilterChange({ subject_id: '', topic_ids: [], exclusive: false })}>All</Chip>
          {subjects.map(s => (
            <Chip
              key={s.id}
              active={String(filters.subject_id) === String(s.id)}
              onClick={() => pickSubject(s)}
            >
              {s.name}
            </Chip>
          ))}
        </div>
      </Row>

      <Row label="Search">
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={kwInput}
            onChange={e => setKwInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') submitKw() }}
            placeholder="Search topic, subtopic, tag, school, subject, level, exam type or year"
            className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="button"
            onClick={submitKw}
            className="px-4 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            Search
          </button>
          {filters.search ? (
            <button
              type="button"
              onClick={() => { setKwInput(''); onFilterChange({ search: '' }) }}
              className="px-3 py-1.5 text-sm text-gray-700 border border-gray-300 rounded hover:bg-gray-100"
            >
              Clear
            </button>
          ) : null}
        </div>
      </Row>

      <Row label="Topic">
        {filters.subject_id && filters.stream_id ? (
          topics.length > 0 ? (
            <TopicMultiSelect
              topics={topics}
              selectedIds={filters.topic_ids || []}
              exclusive={filters.exclusive}
              onChange={onFilterChange}
            />
          ) : (
            <div className="text-sm text-gray-500 italic pt-1">No topics for this subject/stream.</div>
          )
        ) : (
          <div className="text-sm text-gray-500 italic pt-1">Select a Stream and Subject to filter by topic.</div>
        )}
      </Row>

      <Row label="Tags">
        <div className="flex flex-col gap-2">
          {selectedTags.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {selectedTags.map(t => (
                <span
                  key={t.id}
                  className="inline-flex items-center gap-1 text-sm px-2.5 py-0.5 border border-amber-300 text-amber-800 rounded-full bg-amber-50"
                >
                  {t.name}
                  <button
                    type="button"
                    onClick={() => removeTag(t.id)}
                    className="text-amber-500 hover:text-red-600"
                    aria-label={`Remove ${t.name}`}
                  >×</button>
                </span>
              ))}
            </div>
          ) : null}
          {tags.length > 0 ? (
            <TagCombobox
              tags={tags}
              selectedIds={selectedTagIds}
              onAdd={addTag}
              placeholder="Filter by tag…"
            />
          ) : (
            <div className="text-sm text-gray-500 italic pt-1">No tags defined yet.</div>
          )}
        </div>
      </Row>

      <Row label="More">
        <div className="flex items-center flex-wrap gap-3">
          <label className="flex items-center gap-2 text-sm">
            <span className="text-gray-500">School</span>
            <select
              value={filters.school_id || ''}
              onChange={e => onFilterChange({ school_id: e.target.value })}
              className="px-2 py-1 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">All schools</option>
              {schools.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <span className="text-gray-500">Year</span>
            <select
              value={filters.year || ''}
              onChange={e => onFilterChange({ year: e.target.value })}
              className="px-2 py-1 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">All years</option>
              {years.map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <span className="text-gray-500">Exam type</span>
            <select
              value={filters.exam_type_id || ''}
              onChange={e => onFilterChange({ exam_type_id: e.target.value })}
              className="px-2 py-1 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">All exam types</option>
              {examTypes.map(e => <option key={e.id} value={e.id}>{e.name}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <span className="text-gray-500">Paper no.</span>
            <input
              type="text"
              value={filters.paper_number || ''}
              onChange={e => onFilterChange({ paper_number: e.target.value })}
              placeholder="e.g. 1, a"
              className="w-24 px-2 py-1 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </label>
        </div>
      </Row>
    </div>
  )
}
