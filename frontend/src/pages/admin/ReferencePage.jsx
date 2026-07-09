import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import SimpleTab from '../../features/reference/tabs/SimpleTab'
import StreamsTab from '../../features/reference/tabs/StreamsTab'
import LevelsTab from '../../features/reference/tabs/LevelsTab'
import TopicsTab from '../../features/reference/tabs/TopicsTab'

const TAB_KEYS = ['school-levels', 'subjects', 'schools', 'exam-types', 'streams', 'levels', 'topics', 'tags']
const TAB_LABELS = {
  'school-levels': 'School Levels',
  'subjects': 'Subjects',
  'schools': 'Schools',
  'exam-types': 'Exam Types',
  'streams': 'Streams',
  'levels': 'Levels',
  'topics': 'Topics & Subtopics',
  'tags': 'Tags',
}

export default function ReferencePage() {
  const [activeTab, setActiveTab] = useState('school-levels')

  const [schoolLevels, setSchoolLevels] = useState([])
  const [subjects, setSubjects] = useState([])
  const [schools, setSchools] = useState([])
  const [examTypes, setExamTypes] = useState([])
  const [streams, setStreams] = useState([])
  const [levels, setLevels] = useState([])
  const [tags, setTags] = useState([])
  const [pageLoading, setPageLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      api.schoolLevels.list(),
      api.subjects.list(),
      api.schools.list(),
      api.examTypes.list(),
      api.streams.list(),
      api.levels.list(),
      api.tags.list(),
    ]).then(([sl, sub, sch, et, str, lev, tg]) => {
      setSchoolLevels(sl)
      setSubjects(sub)
      setSchools(sch)
      setExamTypes(et)
      setStreams(str)
      setLevels(lev)
      setTags(tg)
    }).finally(() => setPageLoading(false))
  }, [])

  async function refresh(key) {
    const loaders = {
      'school-levels': () => api.schoolLevels.list().then(setSchoolLevels),
      'subjects': () => api.subjects.list().then(setSubjects),
      'schools': () => api.schools.list().then(setSchools),
      'exam-types': () => api.examTypes.list().then(setExamTypes),
      'streams': () => api.streams.list().then(setStreams),
      'levels': () => api.levels.list().then(setLevels),
      'tags': () => api.tags.list().then(setTags),
    }
    await loaders[key]?.()
  }

  return (
    <div className="max-w-[90%] mx-auto">
      <h1 className="text-2xl font-semibold text-gray-900 mb-6">Reference Data</h1>

      {/* Tab bar */}
      <div className="border-b border-gray-200 mb-6">
        <nav className="flex gap-0 overflow-x-auto overflow-y-hidden">
          {TAB_KEYS.map((key) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={`px-4 py-3 text-sm font-medium whitespace-nowrap border-b-2 -mb-px transition-colors ${
                activeTab === key
                  ? 'border-blue-600 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              {TAB_LABELS[key]}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      <div className="bg-white rounded-lg shadow p-6">
        {activeTab === 'school-levels' && (
          <SimpleTab
            label="School Level"
            rows={schoolLevels}
            loading={pageLoading}
            onCreate={async (name) => { await api.schoolLevels.create(name); await refresh('school-levels') }}
            onUpdate={async (id, name) => { await api.schoolLevels.update(id, name); await refresh('school-levels') }}
            onDelete={async (id) => { await api.schoolLevels.delete(id); await refresh('school-levels') }}
          />
        )}
        {activeTab === 'subjects' && (
          <SimpleTab
            label="Subject"
            rows={subjects}
            loading={pageLoading}
            onCreate={async (name) => { await api.subjects.create(name); await refresh('subjects') }}
            onUpdate={async (id, name) => { await api.subjects.update(id, name); await refresh('subjects') }}
            onDelete={async (id) => { await api.subjects.delete(id); await refresh('subjects') }}
          />
        )}
        {activeTab === 'schools' && (
          <SimpleTab
            label="School"
            rows={schools}
            loading={pageLoading}
            onCreate={async (name) => { await api.schools.create(name); await refresh('schools') }}
            onUpdate={async (id, name) => { await api.schools.update(id, name); await refresh('schools') }}
            onDelete={async (id) => { await api.schools.delete(id); await refresh('schools') }}
          />
        )}
        {activeTab === 'exam-types' && (
          <SimpleTab
            label="Exam Type"
            rows={examTypes}
            loading={pageLoading}
            onCreate={async (name) => { await api.examTypes.create(name); await refresh('exam-types') }}
            onUpdate={async (id, name) => { await api.examTypes.update(id, name); await refresh('exam-types') }}
            onDelete={async (id) => { await api.examTypes.delete(id); await refresh('exam-types') }}
          />
        )}
        {activeTab === 'streams' && (
          <StreamsTab
            rows={streams}
            schoolLevels={schoolLevels}
            loading={pageLoading}
            onCreate={async (name, slId) => { await api.streams.create(name, slId); await refresh('streams') }}
            onUpdate={async (id, name, slId) => { await api.streams.update(id, name, slId); await refresh('streams') }}
            onDelete={async (id) => { await api.streams.delete(id); await refresh('streams') }}
          />
        )}
        {activeTab === 'levels' && (
          <LevelsTab
            rows={levels}
            schoolLevels={schoolLevels}
            loading={pageLoading}
            onCreate={async (name, sortOrder, slId) => { await api.levels.create(name, sortOrder, slId); await refresh('levels') }}
            onUpdate={async (id, name, sortOrder, slId) => { await api.levels.update(id, name, sortOrder, slId); await refresh('levels') }}
            onDelete={async (id) => { await api.levels.delete(id); await refresh('levels') }}
            onReorder={async (reorderedRows) => {
              await Promise.all(reorderedRows.map((row) => api.levels.update(row.id, row.name, row.sort_order, row.school_level_id)))
              await refresh('levels')
            }}
          />
        )}
        {activeTab === 'topics' && (
          <TopicsTab subjects={subjects} streams={streams} />
        )}
        {activeTab === 'tags' && (
          <SimpleTab
            label="Tag"
            rows={tags}
            loading={pageLoading}
            onCreate={async (name) => { await api.tags.create(name); await refresh('tags') }}
            onUpdate={async (id, name) => { await api.tags.update(id, name); await refresh('tags') }}
            onDelete={async (id) => { await api.tags.delete(id); await refresh('tags') }}
          />
        )}
      </div>
    </div>
  )
}
