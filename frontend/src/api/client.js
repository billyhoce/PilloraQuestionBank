let _onUnauthorized = null

export function setUnauthorizedHandler(fn) {
  _onUnauthorized = fn
}

function friendlyMessage(status, isDelete, detail) {
  if (status === 401) return 'Your session has expired. Please log in again.'
  if (status === 403) return detail || 'Admin access required.'
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

// POST a file to a presigned S3 form. XMLHttpRequest, not fetch: only XHR reports upload progress.
// `fields` go first and the file last, as S3 requires. `onProgress` gets a 0..1 fraction.
// Aborting `signal` aborts the transfer and rejects with { aborted: true }.
function postToS3(url, fields, file, onProgress, signal) {
  return new Promise((resolve, reject) => {
    const form = new FormData()
    Object.entries(fields).forEach(([k, v]) => form.append(k, v))
    form.append('file', file)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)
    if (signal) {
      if (signal.aborted) {
        reject({ status: 0, aborted: true, message: 'Upload cancelled' })
        return
      }
      signal.addEventListener('abort', () => {
        xhr.abort?.()
        reject({ status: 0, aborted: true, message: 'Upload cancelled' })
      }, { once: true })
    }
    xhr.upload.onprogress = (e) => {
      if (onProgress && e.lengthComputable) onProgress(e.loaded / e.total)
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        if (onProgress) onProgress(1)
        resolve()
      } else {
        reject({ status: xhr.status, message: 'Upload to storage failed. Please try again.' })
      }
    }
    xhr.onerror = () => reject({ status: 0, message: 'Upload to storage failed. Please check your connection and try again.' })
    xhr.send(form)
  })
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
    // Auto-detect: upload a PDF straight to S3 as an ingest job -> { job_id }.
    // 1. POST /uploads (creates the job `awaiting_upload` + a presigned POST), 2. XHR POST to S3 with
    // progress, 3. POST /jobs/{id}/uploaded (queues it). If step 2 or 3 fails, or `signal` is
    // aborted during them, the job is cancelled. `onJob(job_id)` is told the id once it exists.
    uploadJob: async (file, onProgress, { signal, onJob } = {}) => {
      const { job_id, url, fields } = await request('POST', '/api/import/uploads', {
        filename: file.name,
        size: file.size,
      })
      onJob?.(job_id)
      try {
        await postToS3(url, fields, file, onProgress, signal)
        await request('POST', `/api/import/jobs/${job_id}/uploaded`)
      } catch (e) {
        await request('DELETE', `/api/import/jobs/${job_id}`).catch(() => {})
        throw e
      }
      return { job_id }
    },
    // Every admin's jobs, newest first; optional status, `{ job_id }` or `{ paper_id }` filters.
    // Resolves to { jobs, workerAlive, heartbeatAgeS } (the worker's liveness comes with the list).
    listJobs: (status, { job_id, paper_id, unmatched_answers } = {}) => {
      const params = new URLSearchParams()
      if (status) params.set('status', status)
      if (job_id) params.set('job_id', job_id)
      if (paper_id) params.set('paper_id', paper_id)
      if (unmatched_answers) params.set('unmatched_answers', 'true')
      const qs = params.toString()
      return request('GET', `/api/import/jobs${qs ? `?${qs}` : ''}`).then(r => ({
        jobs: r.data,
        workerAlive: r.worker_alive,
        heartbeatAgeS: r.heartbeat_age_s,
      }))
    },
    getJob: (id) => request('GET', `/api/import/jobs/${id}`),
    // The proposal under review, with presigned page-image URLs and pixel sizes.
    review: (id) => request('GET', `/api/import/jobs/${id}/review`),
    // Save the corrected proposal ({papers: [{questions, orphan_answers}]}); 422 carries a message.
    saveProposal: (id, body) => request('PUT', `/api/import/jobs/${id}/proposal`, body),
    // Record the admin's sidebar edits for one paper (its `key`) on its ingest_paper row.
    savePaperMetadata: (id, key, body) =>
      request('PUT', `/api/import/jobs/${id}/papers/${encodeURIComponent(key)}/metadata`, body),
    // Booklet pages first..last of the job's source PDF, as the Manual flow's upload result.
    manualPages: (id, first_page, last_page) =>
      request('POST', `/api/import/jobs/${id}/manual-pages`, { first_page, last_page }),
    // Confirm / skip one proposed paper (paper_label = the paper's `key` from the review).
    // Confirm resolves like `confirm` plus job_status; skip to { job_status }.
    confirmJobPaper: (id, payload) => request('POST', `/api/import/jobs/${id}/confirm`, payload),
    skipJobPaper: (id, paper_label) => request('POST', `/api/import/jobs/${id}/skip`, { paper_label }),
    // Attach an answer-only paper to an existing paper: { key, paper_id, mode? } -> { attached, unmatched, modes, job_status }.
    attachJobPaper: (id, payload) => request('POST', `/api/import/jobs/${id}/attach`, payload),
    // "Match this paper": the booklets paper `key` could be paired with, ranked against `query`
    // (the seven fields, or new_school_name; blank = any) -> { exact, best }.
    paperCandidates: (id, key, query = {}) => {
      const params = new URLSearchParams()
      for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== '') params.set(k, v)
      const qs = params.toString()
      return request('GET', `/api/import/jobs/${id}/papers/${encodeURIComponent(key)}/candidates${qs ? `?${qs}` : ''}`)
    },
    // Pair paper `key` with a pending paper of the other role (another job's, or this one's),
    // optionally saving this paper's `metadata` and the answer `mapping` too. Returns { matches, proposal }.
    matchJobPaper: (id, key, ingest_paper_id, metadata, mapping) =>
      request('POST', `/api/import/jobs/${id}/papers/${encodeURIComponent(key)}/match`, {
        ingest_paper_id, ...(metadata && { metadata }), ...(mapping && { mapping }),
      }),
    // The answer mapping table for paper `key` and `target` ({ ingest_paper_id } or { paper_id };
    // null: its current link) -> { questions, answers, mapping }.
    answerMappingTable: (id, key, target) => {
      const params = new URLSearchParams()
      for (const [k, v] of Object.entries(target ?? {})) params.set(k, v)
      const qs = params.toString()
      return request('GET', `/api/import/jobs/${id}/papers/${encodeURIComponent(key)}/answer-map${qs ? `?${qs}` : ''}`)
    },
    // "Check answers…": save a linked pair's edited mapping -> { matches, proposal }.
    saveAnswerMap: (id, key, mapping) =>
      request('PUT', `/api/import/jobs/${id}/papers/${encodeURIComponent(key)}/answer-map`, { mapping }),
    // Unmatch a linked paper (either side): the pair is rejected for good and both are re-matched.
    // Returns what this paper has now: { matches, proposal }.
    unmatchJobPaper: (id, key) => request('DELETE', `/api/import/jobs/${id}/papers/${encodeURIComponent(key)}/match`),
    // "Not this one": reject an answer-only paper's proposed confirmed paper and re-match it.
    // Returns { matches, proposal } like unmatchJobPaper.
    rejectProposedPaper: (id, key) =>
      request('DELETE', `/api/import/jobs/${id}/papers/${encodeURIComponent(key)}/proposed-paper`),
    // "Not a pair": reject the question paper suggested for answer-only paper `key` and re-match
    // both. Returns { matches, proposal } like unmatchJobPaper.
    rejectSuggestion: (id, key) =>
      request('DELETE', `/api/import/jobs/${id}/papers/${encodeURIComponent(key)}/suggestion`),
    // "This is an answer booklet" / "This is a question booklet": role 'answer_only' | 'question'.
    // Returns { role, matches, proposal }.
    switchPaperRole: (id, key, role) =>
      request('POST', `/api/import/jobs/${id}/papers/${encodeURIComponent(key)}/role`, { role }),
    cancelJob: (id) => request('DELETE', `/api/import/jobs/${id}`),
    // Failed/blocked tasks and everything downstream go back to ready.
    retryJob: (id) => request('POST', `/api/import/jobs/${id}/retry`),
    confirm: (payload) => request('POST', '/api/import/confirm', payload),
    aiTopicsForQuestion: (question_id, signal) =>
      request('POST', '/api/import/ai-topics', { question_id }, signal),
    saveTopics: (paper_id, questions) =>
      request('POST', '/api/import/save-topics', { paper_id, questions }),
    deletePaper: (paper_id) =>
      request('DELETE', `/api/import/papers/${paper_id}`),
  },

  auth: {
    me: () => request('GET', '/api/auth/me'),
    login: (email, password) => request('POST', '/api/auth/login', { email, password }),
    // payload: { first_name, last_name, email, password }
    register: (payload) => request('POST', '/api/auth/register', payload),
    logout: () => request('POST', '/api/auth/logout'),
    // Which third-party sign-in methods this deployment has configured.
    providers: () => request('GET', '/api/auth/providers'),
  },

  users: {
    list: () => request('GET', '/api/users').then(r => r.data),
    // Pre-create an account for someone who hasn't signed up yet, so their
    // premium is live when they do. body: { email, first_name, last_name, role,
    // school_level_ids }. The row has no password until they claim it.
    create: (body) => request('POST', '/api/users', body),
    remove: (id) => request('DELETE', `/api/users/${id}`),
    updateRole: (id, role) => request('PATCH', `/api/users/${id}/role`, { role }),
    // Replaces the user's premium school levels wholesale — send every ticked box.
    setPremiumSchoolLevels: (id, schoolLevelIds) =>
      request('PUT', `/api/users/${id}/premium-school-levels`, { school_level_ids: schoolLevelIds }),
  },

  schoolLevels: {
    list: () => request('GET', '/api/school-levels').then(r => r.data),
    create: (name) => request('POST', '/api/school-levels', { name }),
    update: (id, name) => request('PUT', `/api/school-levels/${id}`, { name }),
    delete: (id) => request('DELETE', `/api/school-levels/${id}`),
  },

  subjects: {
    list: () => request('GET', '/api/subjects').then(r => r.data),
    create: (name, code) => request('POST', '/api/subjects', { name, code }),
    update: (id, name, code) => request('PUT', `/api/subjects/${id}`, { name, code }),
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
      append('paper_number', filters.paper_number)
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

  // Admin-set generation presets + the cover-title list, readable by any
  // authenticated user ({ titles, subtitle1_placeholder, subtitle2_placeholder,
  // cover_body, header_text, additional_instructions, footer_text }); writes are
  // admin-only.
  generationConfig: {
    get: (signal) => request('GET', '/api/generation-config', undefined, signal),
    update: (body) => request('PUT', '/api/generation-config', body),
  },

  // Site-wide settings ({ about_content, protect_images }). The GET is public —
  // the About page and the Browse page both need it while signed out. The PUT is
  // admin-only and *partial*: send only the field you are changing, so the About
  // editor and the image toggle can't overwrite each other.
  siteConfig: {
    get: (signal) => request('GET', '/api/site-config', undefined, signal),
    update: (body) => request('PUT', '/api/site-config', body),
  },

  coverTitles: {
    list: () => request('GET', '/api/cover-titles').then(r => r.data),
    create: (name) => request('POST', '/api/cover-titles', { name }),
    update: (id, name) => request('PUT', `/api/cover-titles/${id}`, { name }),
    delete: (id) => request('DELETE', `/api/cover-titles/${id}`),
  },

  generate: {
    // Auto-select questions for a target (marks total or question count).
    // body: { filters, target_type, target_value, algorithm, exclude_question_ids }
    select: (body, signal) => request('POST', '/api/generate/select', body, signal),
    // Render a PDF. body: { question_ids, variant: "question"|"answer"|"combined",
    // additional_instructions, header_text, footer_text, include_cover, cover_title,
    // cover_subtitle1, cover_subtitle2, cover_body }. An omitted header_text falls
    // back to the config preset. Non-admins may only send the title (from the
    // configured list) and subtitles — the server forces the config
    // presets for everything else. Returns a Blob (binary) — bypasses `request`, which
    // is JSON-only.
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
    setPremium: (id, is_premium) => request('PATCH', `/api/papers/${id}/premium`, { is_premium }),
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
