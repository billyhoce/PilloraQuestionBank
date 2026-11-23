import { callLabel, formatInput, formatTokens, formatUsd, modelName, runTag } from './costFormat'

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

// The job's Claude cost: a one-line total, and a collapsible table of every call in the order
// made. A job from before calls were itemised has only a total.
export default function JobCost({ cost }) {
  if (!cost) return null
  const itemised = cost.calls > 0
  const summary = (
    <>
      Claude cost: <span className="font-medium text-gray-800">{formatUsd(cost.total_usd, { precise: true })}</span>
      {' · '}{itemised ? plural(cost.calls, 'call') : 'per-call breakdown not recorded'}
      {cost.unpriced && <span className="text-amber-700"> · some calls have no price, so the total is low</span>}
    </>
  )
  if (!itemised) return <p className="mb-2 text-xs text-gray-600">{summary}</p>

  const cell = 'py-1 pr-3'
  const num = `${cell} text-right tabular-nums whitespace-nowrap`
  return (
    <details className="mb-2 text-xs text-gray-600">
      <summary className="cursor-pointer">{summary}</summary>
      <table className="mt-1 w-full max-w-3xl" aria-label="Claude calls">
        <thead>
          <tr className="text-left text-gray-500">
            <th className={`${cell} font-medium`}>Call</th>
            <th className={`${cell} font-medium`}>Model</th>
            <th className={`${num} font-medium`}>In (cached)</th>
            <th className={`${num} font-medium`}>Out</th>
            <th className={`${num} font-medium`}>Cost</th>
          </tr>
        </thead>
        <tbody>
          {cost.items.map(item => {
            const tag = runTag(item)
            return (
              <tr key={item.id} className="border-t border-gray-100">
                <td className={cell}>
                  {callLabel(item)}
                  {tag && <span className="ml-2 rounded bg-gray-200 px-1 text-[10px] text-gray-700">{tag}</span>}
                </td>
                <td className={cell} title={item.model || undefined}>{modelName(item.model)}</td>
                <td className={num}>{formatInput(item.input_tokens, item.cache_hit)}</td>
                <td className={num}>{formatTokens(item.output_tokens)}</td>
                <td className={num}>{formatUsd(item.cost_usd, { precise: true })}</td>
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr className="border-t border-gray-300 font-medium text-gray-800">
            <td className={cell}>Total</td>
            <td className={cell} />
            <td className={num}>{formatInput(cost.input_tokens, cost.cache_hit)}</td>
            <td className={num}>{formatTokens(cost.output_tokens)}</td>
            <td className={num}>{formatUsd(cost.total_usd, { precise: true })}</td>
          </tr>
        </tfoot>
      </table>
    </details>
  )
}
