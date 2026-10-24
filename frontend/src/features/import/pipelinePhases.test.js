import { describe, it, expect } from 'vitest'
import { PHASES, jobPhase, phaseCaption } from './pipelinePhases'

const idx = id => PHASES.findIndex(p => p.id === id)

describe('pipelinePhases', () => {
  it('places each status and stage on a step', () => {
    expect(jobPhase({ status: 'awaiting_upload' })).toEqual({ current: idx('upload'), state: 'active' })
    expect(jobPhase({ status: 'queued', stage: null })).toEqual({ current: idx('read'), state: 'waiting' })
    expect(jobPhase({ status: 'running', stage: 'segment' })).toEqual({ current: idx('find'), state: 'active' })
    for (const stage of ['scan', 'locate', 'render', 'grid', 'ocr', 'questions']) {
      expect(jobPhase({ status: 'running', stage }).current).toBe(idx('extract'))
    }
    expect(jobPhase({ status: 'running', stage: 'report' }).current).toBe(idx('assemble'))
    expect(jobPhase({ status: 'review_ready', stage: 'report' })).toEqual({ current: PHASES.length, state: 'done' })
  })

  it('puts a failure on its stage, from the error when the stage is unknown', () => {
    expect(jobPhase({ status: 'failed', stage: 'split' })).toEqual({ current: idx('split'), state: 'failed' })
    expect(jobPhase({ status: 'failed', stage: null, error: 'segment failed: boom' }).current).toBe(idx('find'))
  })

  it('captions the step in hand', () => {
    expect(phaseCaption({ status: 'running', stage: 'ocr', tasks_done: 3, tasks_total: 8 })).toBe('Extract questions · 3/8 tasks')
    expect(phaseCaption({ status: 'queued' })).toBe('Waiting for the worker')
    expect(phaseCaption({ status: 'failed', stage: 'register' })).toBe('Failed at Read PDF')
    expect(phaseCaption({ status: 'review_ready' })).toBe('Done')
  })
})
