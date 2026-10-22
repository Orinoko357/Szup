/** Przełącznik segmentowy (filtr widoku) — jeden wygląd w całej aplikacji.
 *  options: [{ value, label, count? }] */
export default function Segmented({ options, value, onChange, ariaLabel }) {
  return (
    <div role="group" aria-label={ariaLabel} className="segmented">
      {options.map(o => (
        <button key={o.value} type="button" aria-pressed={value === o.value}
                className={`segmented__btn${value === o.value ? ' is-active' : ''}`}
                onClick={() => onChange(o.value)}>
          {o.label}
          {o.count != null && <span className="segmented__count">{o.count}</span>}
        </button>
      ))}
    </div>
  )
}
