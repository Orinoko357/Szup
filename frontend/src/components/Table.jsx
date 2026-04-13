import Pagination from './Pagination';

export default function Table({ columns, data, loading, total, page, limit, onPageChange, emptyMessage = 'Brak danych' }) {
  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              {columns.map(col => (
                <th
                  key={col.key}
                  className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider"
                  style={col.width ? { width: col.width } : {}}
                >
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-100">
            {loading ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center">
                  <div className="inline-block animate-spin h-6 w-6 border-4 border-primary-500 border-t-transparent rounded-full" />
                </td>
              </tr>
            ) : data.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center text-sm text-gray-500">
                  {emptyMessage}
                </td>
              </tr>
            ) : data.map((row, i) => (
              <tr key={row.id ?? i} className="hover:bg-gray-50">
                {columns.map(col => (
                  <td key={col.key} className="px-4 py-3 text-sm text-gray-700 whitespace-nowrap">
                    {col.render ? col.render(row[col.key], row) : (row[col.key] ?? '—')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {total !== undefined && onPageChange && (
        <div className="px-4 py-3 border-t border-gray-200">
          <Pagination total={total} page={page} limit={limit} onChange={onPageChange} />
        </div>
      )}
    </div>
  );
}
