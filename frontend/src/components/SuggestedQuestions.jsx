const QUESTIONS = [
  'Which airports in New England are strong candidates for terminal expansion?',
  'Compare LA and Santa Ana airport congestion levels.',
  'What is the percentage of long haul flights out of Anchorage airport?',
  'What is the unmet flight demand in SFO airport and why?',
]

function SuggestedQuestions({ onSelect, disabled }) {
  return (
    <div className="suggested-questions">
      <p className="suggested-questions-label">Try asking:</p>
      <div className="suggested-questions-chips">
        {QUESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            className="chip"
            onClick={() => onSelect(q)}
            disabled={disabled}
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}

export default SuggestedQuestions
