import { cloneElement, isValidElement, useId } from 'react'

/** Pole formularza z etykietą powiązaną przez htmlFor/id (czytniki ekranu).
 *  Użycie: <Field label="Nazwa" required hint="…"><input className="form-control" … /></Field> */
export default function Field({ label, required, hint, children, style }) {
  const id = useId()
  const child = isValidElement(children) ? cloneElement(children, { id: children.props.id || id }) : children
  return (
    <div className="form-group" style={style}>
      <label htmlFor={isValidElement(children) ? (children.props.id || id) : undefined} className="form-label">
        {label}{required && <span aria-hidden="true" style={{ color: 'var(--color-error)' }}> *</span>}
      </label>
      {child}
      {hint && <div className="form-hint">{hint}</div>}
    </div>
  )
}
