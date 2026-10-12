/**
 * Sygnet rodziny aplikacji WODS — Identyfikacja wizualna UM Wodzisławia Śląskiego.
 *
 * Zasada: stały granatowy kwadrat + zmienny złoty glif identyfikujący aplikację.
 * Glif dla SZUP to trójkąt (clip-path). Proporcje glifu ≈ 30% pola.
 *
 * Props:
 *   size      — bok granatowego kwadratu (px), domyślnie 32
 *   onNavy    — true, gdy sygnet leży na granatowym tle (header/sidebar):
 *               pole robi się półprzezroczyste białe zamiast pełnego granatu.
 */
export default function WodsLogo({ size = 32, onNavy = false }) {
  const glyph = Math.round(size * 0.34)
  return (
    <div style={{
      width: size, height: size, flex: 'none',
      background: onNavy ? 'rgba(255,255,255,0.08)' : 'var(--color-navy)',
      display: 'grid', placeItems: 'center',
    }}>
      <div style={{
        width: glyph + 2, height: glyph,
        background: 'var(--color-gold)',
        clipPath: 'polygon(50% 0, 100% 100%, 0 100%)',
      }} />
    </div>
  )
}
