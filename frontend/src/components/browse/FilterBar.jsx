import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import TopicMultiSelect from './TopicMultiSelect'

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
  const [topics, setTopics] = useState([])
  const [years, setYears] = useState([])
  const [kwInput, setKwInput] = useState(filters.subtopic_keyword || '')

  useEffect(() => {
    Promise.all([
      api.levels.list(),
      api.streams.list(),
      api.subjects.list(),
      api.schools.list(),
      api.examTypes.list(),
    ]).then(([lv, st, su, sc, et]) => {
      setLevels(lv || [])
      setStreams(st || [])
      setSubjects(su || [])
      setSchools(sc || [])
      setExamTypes(et || [])
    }).catch(() => {})
  }, [])

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
    setKwInput(filters.subtopic_keyword || '')
  }, [filters.subtopic_keyword])

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
    onFilterChange({ subtopic_keyword: kwInput.trim() })
  }

  const visibleStreams = selectedLevel
    ? streams.filter(s => s.school_level_id === selectedLevel.school_level_id)
    : streams

  return (
    <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 space-y-1">
      <Row label="Level">
        <div className="flex items-center flex-wrap gap-2">
          <Chip active={!filters.level_id} onClick={() => onFilterChange({ level_id: '' })}>All</Chip>
          {levels.map(l => (
            <Chip
              key={l.id}
              active={String(filters.level_id) === String(l.id)}
              onClick={() => pickLevel(l)}
            >
              {l.name}
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
            placeholder="Subtopic keyword e.g. indices, prime factorisation, simultaneous equations"
            className="flex-1 px-3 py-1.5 text-sm border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="button"
            onClick={submitKw}
            className="px-4 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
          >
            Search
          </button>
          {filters.subtopic_keyword ? (
            <button
              type="button"
              onClick={() => { setKwInput(''); onFilterChange({ subtopic_keyword: '' }) }}
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
        </div>
      </Row>
    </div>
  )
}
