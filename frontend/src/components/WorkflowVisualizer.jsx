const STATUS_STYLE = {
  OCZEKUJE:     'border-yellow-400 bg-yellow-50 text-yellow-800',
  ZATWIERDZONY: 'border-green-400 bg-green-50 text-green-800',
  ODRZUCONY:    'border-red-400 bg-red-50 text-red-800',
  'ODESŁANY':   'border-orange-400 bg-orange-50 text-orange-800',
  'POMINIĘTY':  'border-gray-300 bg-gray-50 text-gray-500',
};

const STATUS_ICON = {
  OCZEKUJE: '⏳',
  ZATWIERDZONY: '✓',
  ODRZUCONY: '✗',
  'ODESŁANY': '↩',
  'POMINIĘTY': '⊘',
};

export default function WorkflowVisualizer({ etapy = [], aktualnyEtap }) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {etapy.map((etap, i) => (
        <div key={etap.id || etap.kolejnosc} className="flex items-center gap-2">
          <div
            className={`relative flex flex-col items-center px-3 py-2 rounded-lg border-2 min-w-[120px] text-center text-xs
              ${etap.status ? STATUS_STYLE[etap.status] || 'border-gray-200 bg-white' : 'border-gray-200 bg-white'}
              ${etap.kolejnosc === aktualnyEtap ? 'ring-2 ring-primary-500 ring-offset-1' : ''}
              ${etap.opcjonalny ? 'border-dashed' : ''}
            `}
          >
            <span className="font-semibold text-[11px] leading-tight">
              {STATUS_ICON[etap.status] || ''} Etap {etap.kolejnosc}
            </span>
            <span className="mt-0.5 text-[10px] leading-tight truncate max-w-[110px]">
              {etap.zatwierdzajacy_nazwa || etap.nazwa || '—'}
            </span>
            {etap.opcjonalny && (
              <span className="text-[9px] text-gray-400">(opcjonalny)</span>
            )}
            {etap.data_akcji && (
              <span className="text-[9px] text-gray-400">
                {new Date(etap.data_akcji).toLocaleDateString('pl-PL')}
              </span>
            )}
          </div>
          {i < etapy.length - 1 && (
            <svg className="w-4 h-4 text-gray-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          )}
        </div>
      ))}
      <div className="flex items-center gap-2">
        <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <div className="px-3 py-2 rounded-lg border-2 border-blue-300 bg-blue-50 text-blue-700 text-xs font-semibold">
          IT
        </div>
      </div>
    </div>
  );
}
