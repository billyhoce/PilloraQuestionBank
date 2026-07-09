let _onUnauthorized = null

export function setUnauthorizedHandler(fn) {
  _onUnauthorized = fn
}

function friendlyMessage(status, isDelete, detail) {
  if (status === 401) return 'Your session has expired. Please log in again.'
  if (status === 403) return 'Admin access required.'
  if (status === 409) {
    if (detail) return detail
    if (isDelete) return 'Cannot delete — this item is still in use by other data.'
    return 'This name already exists.'
  }
  if (status === 422) return 'Invalid input. Please check your entries.'
  if (status >= 500) return 'Server error. Please try again in a moment.'
  return detail || 'An unexpected error occurred.'
}

async function request(method, path, body, signal) {
  const isDelete = method === 'DELETE'
  const opts = {
    method,
    credentials: 'include',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
  }
  if (body !== undefined) opts.body = JSON.stringify(body)
  if (signal !== undefined) opts.signal = signal

  const res = await fetch(path, opts)

  if (res.status === 204) return null

  let data = null
  try {
    data = await res.json()
  } catch {
    // non-JSON response
  }

  if (!res.ok) {
    const isLoginEndpoint = path === '/api/auth/login'
    if (res.status === 401 && _onUnauthorized && !isLoginEndpoint) _onUnauthorized()
    const detail = data?.detail ?? ''
    const message = (res.status === 401 && isLoginEndpoint)
      ? 'Unknown email or incorrect password.\nPlease try again.'
      : friendlyMessage(res.status, isDelete, detail)
    throw { status: res.status, message }
  }

  return data
}

export const api = {
  import: {
    uploadPdf: (file) => {
      const form = new FormData()
      form.append('file', file)
      return fetch('/api/import/upload-pdf', { method: 'POST', credentials: 'include', body: form })
        .then(async (res) => {
          if (!res.ok) {
            const data = await res.json().catch(() => null)
            if (res.status === 401 && _onUnauthorized) _onUnauthorized()
            throw { status: res.status, message: data?.detail || 'Upload failed' }
          }
          return res.json()
        })
    },
    confirm: (payload) => request('POST', '/api/import/confirm', payload),
    aiTopicsForQuestion: (question_id, signal) =>
      request('POST', '/api/import/ai-topics', { question_id }, signal),
    saveTopics: (paper_id, question_topics) =>
      request('POST', '/api/import/save-topics', { paper_id, question_topics }),
    deletePaper: (paper_id) =>
      request('DELETE', `/api/import/papers/${paper_id}`),
  },

  auth: {
    me: () => request('GET', '/api/auth/me'),
    login: (email, password) => request('POST', '/api/auth/login', { email, password }),
    register: (email, password) => request('POST', '/api/auth/register', { email, password }),
    logout: () => request('POST', '/api/auth/logout'),
  },

  schoolLevels: {
    list: () => request('GET', '/api/school-levels').then(r => r.data),
    create: (name) => request('POST', '/api/school-levels', { name }),
    update: (id, name) => request('PUT', `/api/school-levels/${id}`, { name }),
    delete: (id) => request('DELETE', `/api/school-levels/${id}`),
  },

  subjects: {
    list: () => request('GET', '/api/subjects').then(r => r.data),
    create: (name) => request('POST', '/api/subjects', { name }),
    update: (id, name) => request('PUT', `/api/subjects/${id}`, { name }),
    delete: (id) => request('DELETE', `/api/subjects/${id}`),
  },

  schools: {
    list: () => request('GET', '/api/schools').then(r => r.data),
    create: (name) => request('POST', '/api/schools', { name }),
    update: (id, name) => request('PUT', `/api/schools/${id}`, { name }),
    delete: (id) => request('DELETE', `/api/schools/${id}`),
  },

  examTypes: {
    list: () => request('GET', '/api/exam-types').then(r => r.data),
    create: (name) => request('POST', '/api/exam-types', { name }),
    update: (id, name) => request('PUT', `/api/exam-types/${id}`, { name }),
    delete: (id) => request('DELETE', `/api/exam-types/${id}`),
  },

  streams: {
    list: () => request('GET', '/api/streams').then(r => r.data),
    create: (name, school_level_id) => request('POST', '/api/streams', { name, school_level_id }),
    update: (id, name, school_level_id) => request('PUT', `/api/streams/${id}`, { name, school_level_id }),
    delete: (id) => request('DELETE', `/api/streams/${id}`),
  },

  levels: {
    list: () => request('GET', '/api/levels').then(r => r.data),
    create: (name, sort_order, school_level_id) =>
      request('POST', '/api/levels', { name, sort_order, school_level_id }),
    update: (id, name, sort_order, school_level_id) =>
      request('PUT', `/api/levels/${id}`, { name, sort_order, school_level_id }),
    delete: (id) => request('DELETE', `/api/levels/${id}`),
  },

  topics: {
    list: (subject_id, stream_id) =>
      request('GET', `/api/topics?subject_id=${subject_id}&stream_id=${stream_id}`).then(r => r.data),
    sync: (subject_id, stream_id, topics) =>
      request('PUT', '/api/topics/sync', { subject_id, stream_id, topics }).then(r => r.data),
  },

  subtopics: {
    list: (topic_id) => request('GET', `/api/subtopics?topic_id=${topic_id}`).then(r => r.data),
  },

  tags: {
    list: () => request('GET', '/api/tags').then(r => r.data),
    create: (name) => request('POST', '/api/tags', { name }),
    update: (id, name) => request('PUT', `/api/tags/${id}`, { name }),
    delete: (id) => request('DELETE', `/api/tags/${id}`),
  },

  questions: {
    list: (filters = {}, signal) => {
      const params = new URLSearchParams()
      const append = (k, v) => {
        if (v === undefined || v === null || v === '') return
        params.append(k, v)
      }
      append('subject_id', filters.subject_id)
      append('stream_id', filters.stream_id)
      append('level_id', filters.level_id)
      append('school_id', filters.school_id)
      append('exam_type_id', filters.exam_type_id)
      append('year', filters.year)
      append('search', filters.search)
      if (filters.exclusive) params.append('exclusive', 'true')
      for (const id of filters.topic_ids || []) params.append('topic_ids', id)
      for (const id of filters.tag_ids || []) params.append('tag_ids', id)
      append('page', filters.page ?? 1)
      append('page_size', filters.page_size ?? 50)
      const qs = params.toString()
      return request('GET', `/api/questions${qs ? `?${qs}` : ''}`, undefined, signal)
    },
    get: (id, signal) => request('GET', `/api/questions/${id}`, undefined, signal),
  },

  generate: {
    // Auto-select a randomized set of questions summing near target_marks.
    // body: { filters, target_marks, exclude_question_ids }
    select: (body, signal) => request('POST', '/api/generate/select', body, signal),
    // Render one PDF variant. body: { question_ids, variant, header_text }.
    // Returns a Blob (binary) — bypasses `request`, which is JSON-only.
    paper: async (body) => {
      const res = await fetch('/api/generate/paper', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => null)
        if (res.status === 401 && _onUnauthorized) _onUnauthorized()
        throw { status: res.status, message: friendlyMessage(res.status, false, data?.detail ?? '') }
      }
      return res.blob()
    },
  },

  papers: {
    years: ({ subject_id, stream_id, level_id } = {}) => {
      const params = new URLSearchParams()
      if (subject_id) params.append('subject_id', subject_id)
      if (stream_id) params.append('stream_id', stream_id)
      if (level_id) params.append('level_id', level_id)
      const qs = params.toString()
      return request('GET', `/api/papers/years${qs ? `?${qs}` : ''}`).then(r => r.data)
    },

    list: (filters = {}) => {
      const params = new URLSearchParams()
      const append = (k, v) => {
        if (v === undefined || v === null || v === '') return
        params.append(k, v)
      }
      append('subject_id', filters.subject_id)
      append('stream_id', filters.stream_id)
      append('level_id', filters.level_id)
      append('school_id', filters.school_id)
      append('exam_type_id', filters.exam_type_id)
      append('year', filters.year)
      append('page', filters.page ?? 1)
      append('page_size', filters.page_size ?? 50)
      const qs = params.toString()
      return request('GET', `/api/papers${qs ? `?${qs}` : ''}`)
    },
    get: (id) => request('GET', `/api/papers/${id}`),
    update: (id, metadata) => request('PUT', `/api/papers/${id}`, metadata),
    remove: (id) => request('DELETE', `/api/papers/${id}`),
    addQuestion: (paperId, payload) => request('POST', `/api/papers/${paperId}/questions`, payload),
    updateQuestion: (questionId, payload) => request('PUT', `/api/questions/${questionId}`, payload),
    deleteQuestion: (questionId) => request('DELETE', `/api/questions/${questionId}`),
    setQuestionTags: (questionId, tag_ids) => request('PUT', `/api/questions/${questionId}/tags`, { tag_ids }),
    uploadImage: (file) => {
      const form = new FormData()
      form.append('file', file)
      return fetch('/api/papers/upload-image', { method: 'POST', credentials: 'include', body: form })
        .then(async (res) => {
          if (!res.ok) {
            const data = await res.json().catch(() => null)
            if (res.status === 401 && _onUnauthorized) _onUnauthorized()
            throw { status: res.status, message: data?.detail || 'Image upload failed' }
          }
          return res.json()
        })
    },
  },
}
