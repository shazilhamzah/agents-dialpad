'use strict';

(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.FilesUtil = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  function joinPath(dir, name) {
    if (!dir) return name || '';
    if (!name) return dir || '';
    const cleanDir = dir.replace(/\/+$/, '');
    const cleanName = name.replace(/^\/+/, '');
    return `${cleanDir}/${cleanName}`;
  }

  function crumbs(project, path) {
    const res = [];
    const projLabel = project || 'root';
    res.push({ name: projLabel, path: '' });
    if (!path) return res;

    const parts = path.split('/').filter(Boolean);
    let cur = '';
    for (const part of parts) {
      cur = cur ? `${cur}/${part}` : part;
      res.push({ name: part, path: cur });
    }
    return res;
  }

  function humanSize(n) {
    if (n == null || Number.isNaN(n) || n === 0) return '0 B';
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) {
      const kb = n / 1024;
      return kb < 10 ? `${kb.toFixed(1)} KB` : `${Math.round(kb)} KB`;
    }
    const mb = n / (1024 * 1024);
    if (mb < 100) return `${mb.toFixed(1)} MB`;
    return `${Math.round(mb)} MB`;
  }

  function ago(ts) {
    if (!ts) return '';
    const s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 60) return 'just now';
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return `${Math.floor(s / 86400)}d ago`;
  }

  function sniffDelimiter(line) {
    if (!line) return ',';
    let commas = 0, semicolons = 0, tabs = 0;
    let inQuotes = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (c === '"') {
        inQuotes = !inQuotes;
      } else if (!inQuotes) {
        if (c === ',') commas++;
        else if (c === ';') semicolons++;
        else if (c === '\t') tabs++;
      }
    }
    if (tabs > commas && tabs > semicolons) return '\t';
    if (semicolons > commas && semicolons >= tabs) return ';';
    return ',';
  }

  function parseCSV(text) {
    if (!text || !text.trim()) return [];
    const firstLine = text.split(/\r\n|\r|\n/)[0];
    const delim = sniffDelimiter(firstLine);

    const rows = [];
    let curRow = [];
    let curField = '';
    let inQuotes = false;
    let i = 0;

    while (i < text.length) {
      const c = text[i];
      if (inQuotes) {
        if (c === '"') {
          if (i + 1 < text.length && text[i + 1] === '"') {
            curField += '"';
            i += 2;
            continue;
          } else {
            inQuotes = false;
            i++;
            continue;
          }
        } else {
          curField += c;
          i++;
        }
      } else {
        if (c === '"') {
          inQuotes = true;
          i++;
        } else if (c === delim) {
          curRow.push(curField);
          curField = '';
          i++;
        } else if (c === '\r') {
          if (i + 1 < text.length && text[i + 1] === '\n') {
            i++;
          }
          curRow.push(curField);
          curField = '';
          rows.push(curRow);
          curRow = [];
          i++;
        } else if (c === '\n') {
          curRow.push(curField);
          curField = '';
          rows.push(curRow);
          curRow = [];
          i++;
        } else {
          curField += c;
          i++;
        }
      }
    }

    if (curField.length > 0 || curRow.length > 0) {
      curRow.push(curField);
      rows.push(curRow);
    }

    return rows;
  }

  function chunkLines(lines, chunkSize = 500) {
    if (!Array.isArray(lines)) return [];
    const chunks = [];
    for (let i = 0; i < lines.length; i += chunkSize) {
      chunks.push(lines.slice(i, i + chunkSize));
    }
    return chunks;
  }

  return {
    joinPath,
    crumbs,
    humanSize,
    ago,
    sniffDelimiter,
    parseCSV,
    chunkLines,
  };
});
