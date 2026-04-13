'use strict';
const ExcelJS = require('exceljs');

/**
 * Generate an Excel workbook from data.
 * columns: [{ header, key, width }]
 * rows: array of objects
 */
async function generateXlsx(columns, rows, sheetName = 'Dane') {
  const workbook = new ExcelJS.Workbook();
  workbook.creator = 'System ZUP';
  workbook.created = new Date();

  const sheet = workbook.addWorksheet(sheetName);
  sheet.columns = columns.map(c => ({
    header: c.header,
    key: c.key,
    width: c.width || 20,
  }));

  // Style header row
  const headerRow = sheet.getRow(1);
  headerRow.font = { bold: true, color: { argb: 'FFFFFFFF' } };
  headerRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF2563EB' } };
  headerRow.alignment = { vertical: 'middle', horizontal: 'center' };
  headerRow.height = 22;

  // Add data
  for (const row of rows) {
    sheet.addRow(row);
  }

  // Borders
  sheet.eachRow((row) => {
    row.eachCell((cell) => {
      cell.border = {
        top: { style: 'thin' },
        left: { style: 'thin' },
        bottom: { style: 'thin' },
        right: { style: 'thin' },
      };
    });
  });

  return workbook;
}

/**
 * Send xlsx as HTTP response.
 */
async function sendXlsxResponse(res, columns, rows, filename, sheetName) {
  const workbook = await generateXlsx(columns, rows, sheetName);
  res.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
  res.setHeader('Content-Disposition', `attachment; filename="${filename}.xlsx"`);
  await workbook.xlsx.write(res);
  res.end();
}

/**
 * Send CSV as HTTP response.
 */
function sendCsvResponse(res, columns, rows, filename) {
  res.setHeader('Content-Type', 'text/csv; charset=utf-8');
  res.setHeader('Content-Disposition', `attachment; filename="${filename}.csv"`);
  res.write('\uFEFF'); // BOM for Excel
  const headers = columns.map(c => `"${c.header}"`).join(';');
  res.write(headers + '\n');
  for (const row of rows) {
    const line = columns.map(c => {
      const val = row[c.key];
      if (val === null || val === undefined) return '""';
      return `"${String(val).replace(/"/g, '""')}"`;
    }).join(';');
    res.write(line + '\n');
  }
  res.end();
}

module.exports = { generateXlsx, sendXlsxResponse, sendCsvResponse };
