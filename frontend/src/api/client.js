let _onUnauthorized = null

export function setUnauthorizedHandler(fn) {
  _onUnauthorized = fn
}

function friendlyMessage(status, isDelete, detail) {
  if (status === 401) return 'Your session has expired. Please log in again.'
  if (status === 403) return 'Admin access required.'
  if (status === 409) {
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
    create: (subject_id, stream_id, name, topic_number) =>
      request('POST', '/api/topics', { subject_id, stream_id, name, topic_number }),
    update: (id, subject_id, stream_id, name, topic_number) =>
      request('PUT', `/api/topics/${id}`, { subject_id, stream_id, name, topic_number }),
    delete: (id) => request('DELETE', `/api/topics/${id}`),
  },

  subtopics: {
    list: (topic_id) => request('GET', `/api/subtopics?topic_id=${topic_id}`).then(r => r.data),
    create: (topic_id, name) => request('POST', '/api/subtopics', { topic_id, name }),
    update: (id, topic_id, name) => request('PUT', `/api/subtopics/${id}`, { topic_id, name }),
    delete: (id) => request('DELETE', `/api/subtopics/${id}`),
  },
}
