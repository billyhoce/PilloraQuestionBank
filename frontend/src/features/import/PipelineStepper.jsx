import { PHASES } from './pipelinePhases'

const DOT = {
  done: 'bg-green-500 border-green-500',
  active: 'bg-blue-600 border-blue-600 animate-pulse',
  waiting: 'bg-white border-blue-400',
  failed: 'bg-red-600 border-red-600',
  todo: 'bg-white border-gray-300',
}

// The pipeline's steps as a row of dots: green behind, blue (pulsing) in hand, red where it
// failed, grey ahead. `current` / `state` come from jobPhase().
export default function PipelineStepper({ current, state, label }) {
  return (
    <ol aria-label={label} className="flex items-center gap-1">
      {PHASES.map((p, i) => {
        const s = i < current || state === 'done' ? 'done' : i === current ? state : 'todo'
        return (
          <li key={p.id} data-phase={p.id} data-state={s} title={p.label} className="flex items-center gap-1">
            <span className={`block w-2.5 h-2.5 rounded-full border-2 ${DOT[s]}`} />
            <span className={`hidden lg:inline text-[11px] ${i === current && state !== 'done' ? 'text-gray-800 font-medium' : 'text-gray-400'}`}>
              {p.label}
            </span>
            {i < PHASES.length - 1 && <span className={`block w-3 h-px ${i < current ? 'bg-green-400' : 'bg-gray-300'}`} />}
            <span className="sr-only">{`${p.label}: ${s}`}</span>
          </li>
        )
      })}
    </ol>
  )
}
