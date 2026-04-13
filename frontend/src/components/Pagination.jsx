export default function Pagination({ total, page, limit, onChange }) {
  const totalPages = Math.ceil(total / limit);
  if (totalPages <= 1) return null;

  const pages = [];
  const delta = 2;
  for (let i = Math.max(1, page - delta); i <= Math.min(totalPages, page + delta); i++) {
    pages.push(i);
  }

  return (
    <div className="flex items-center justify-between text-sm text-gray-600">
      <span>
        {(page - 1) * limit + 1}–{Math.min(page * limit, total)} z {total}
      </span>
      <div className="flex gap-1">
        <button
          onClick={() => onChange(page - 1)}
          disabled={page <= 1}
          className="px-2 py-1 rounded border border-gray-300 disabled:opacity-40 hover:bg-gray-100"
        >
          ‹
        </button>
        {pages[0] > 1 && (
          <>
            <button onClick={() => onChange(1)} className="px-2 py-1 rounded border border-gray-300 hover:bg-gray-100">1</button>
            {pages[0] > 2 && <span className="px-1">…</span>}
          </>
        )}
        {pages.map(p => (
          <button
            key={p}
            onClick={() => onChange(p)}
            className={`px-2 py-1 rounded border ${p === page ? 'bg-primary-600 text-white border-primary-600' : 'border-gray-300 hover:bg-gray-100'}`}
          >
            {p}
          </button>
        ))}
        {pages[pages.length - 1] < totalPages && (
          <>
            {pages[pages.length - 1] < totalPages - 1 && <span className="px-1">…</span>}
            <button onClick={() => onChange(totalPages)} className="px-2 py-1 rounded border border-gray-300 hover:bg-gray-100">{totalPages}</button>
          </>
        )}
        <button
          onClick={() => onChange(page + 1)}
          disabled={page >= totalPages}
          className="px-2 py-1 rounded border border-gray-300 disabled:opacity-40 hover:bg-gray-100"
        >
          ›
        </button>
      </div>
    </div>
  );
}
