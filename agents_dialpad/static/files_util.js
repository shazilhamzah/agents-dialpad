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

  return {
    joinPath,
    crumbs,
    humanSize,
    ago,
  };
});
