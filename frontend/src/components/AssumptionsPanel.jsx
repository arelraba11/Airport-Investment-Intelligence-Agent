import { useState } from 'react'

const ASSUMPTIONS = [
  'Dataset scope: 80 airports — the top 75 US airports by FAA CY2024 enplanements, plus every New England airport ranked 150th or better nationally.',
  'Congestion capacity: assumes 230,000 flight movements per runway per year, a rough industry-proxy figure, not a measured value.',
  'Long-haul threshold: flights of at least 2,500 great-circle miles are counted as "long-haul".',
  'Unmet demand: a derived heuristic (growth score × 0.6 + congestion score × 0.4), not a directly measured quantity.',
]

function AssumptionsPanel() {
  const [expanded, setExpanded] = useState(true)

  return (
    <div className="assumptions-panel">
      <button
        type="button"
        className="assumptions-toggle"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <span>Assumptions &amp; Data Notes</span>
        <span className="assumptions-caret">{expanded ? '−' : '+'}</span>
      </button>
      {expanded && (
        <ul className="assumptions-list">
          {ASSUMPTIONS.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default AssumptionsPanel
