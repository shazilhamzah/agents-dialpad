/* agents-dialpad Markdown: a small, dependency-free, XSS-safe Markdown -> HTML renderer for chat replies.
 *
 * Supports: headings, paragraphs (newline = <br>), **bold** *italic* ~~strike~~ `code`, links, bare URLs,
 * ordered / unordered / nested / task lists, blockquotes, horizontal rules, GFM tables, fenced code blocks
 * (with a copy button hook) and backslash escapes.
 *
 * Safety: all text is HTML-escaped first; only http(s) and mailto links are linked; images are never loaded
 * (a remote image URL is a classic way to leak data from a model's output), they become plain links.
 * Streaming-friendly: an unclosed code fence is rendered as a code block so far.
 *
 * Works as a browser global (`Markdown`) and as a CommonJS module (for tests).
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Markdown = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const escapeHtml = (s) => String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  /** Returns a normalised http(s)/mailto URL, or null when the URL is not safe to link. */
  function safeUrl(url) {
    const compact = String(url).trim().replace(/^<|>$/g, '').replace(/[\u0000-\u001f\u007f\s]+/g, '');
    return /^(https?:\/\/|mailto:)/i.test(compact) ? compact : null;
  }

  const anchor = (href, innerHtml) =>
    `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer nofollow">${innerHtml}</a>`;

  /* ---------------------------------------------------------------- inline */
  const OPEN = '', CLOSE = '';   // private-use markers for already-rendered fragments

  function inline(src) {
    const stash = [];
    const hold = (html) => OPEN + (stash.push(html) - 1) + CLOSE;
    let s = String(src).replace(/[]/g, '');

    // backslash escapes: \* \_ \` ...
    s = s.replace(/\\([\\`*_{}\[\]()#+\-.!~|>])/g, (m, c) => hold(escapeHtml(c)));

    // code spans
    s = s.replace(/(`+)(?!`)([\s\S]*?[^`])\1(?!`)/g, (m, t, code) => hold('<code>' + escapeHtml(code.trim()) + '</code>'));

    // [text](url "title") and ![alt](url)  (images are never loaded, see header)
    s = s.replace(/(!?)\[([^\]\n]*)\]\(\s*(<[^>\n]*>|[^\s)]*)(?:\s+(?:"[^"\n]*"|'[^'\n]*'))?\s*\)/g, (m, bang, text, url) => {
      const href = safeUrl(url);
      const label = bang ? 'image: ' + (text || 'link') : text;
      return hold(href ? anchor(href, inline(label)) : inline(label));
    });

    // <https://autolinks>
    s = s.replace(/<((?:https?:\/\/|mailto:)[^\s<>]+)>/gi, (m, u) => {
      const href = safeUrl(u);
      return href ? hold(anchor(href, escapeHtml(u))) : m;
    });

    // bare URLs
    s = s.replace(/(^|[^\w\/="'])(https?:\/\/[^\s<>]+)/gi, (m, pre, url) => {
      let trail = '';
      for (;;) {
        const last = url.slice(-1);
        if (/[.,;:!?'"\]*_~]/.test(last)) { trail = last + trail; url = url.slice(0, -1); continue; }
        if (last === ')' && (url.match(/\)/g) || []).length > (url.match(/\(/g) || []).length) { trail = last + trail; url = url.slice(0, -1); continue; }
        break;
      }
      const href = safeUrl(url);
      return href ? pre + hold(anchor(href, escapeHtml(url))) + escapeHtml(trail) : m;
    });

    s = escapeHtml(s);

    // emphasis
    s = s
      .replace(/\*\*\*(?=\S)([\s\S]*?\S)\*\*\*/g, '<strong><em>$1</em></strong>')
      .replace(/\*\*(?=\S)([\s\S]*?\S)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^\w])__(?=\S)([\s\S]*?\S)__(?!\w)/g, '$1<strong>$2</strong>')
      .replace(/(^|[^*\w])\*(?=[^\s*])([\s\S]*?[^\s*])\*(?!\*)/g, '$1<em>$2</em>')
      .replace(/(^|[^\w])_(?=[^\s_])([\s\S]*?[^\s_])_(?!\w)/g, '$1<em>$2</em>')
      .replace(/~~(?=\S)([\s\S]*?\S)~~/g, '<del>$1</del>');

    s = s.replace(/\n/g, '<br>');
    return s.replace(/(\d+)/g, (m, i) => stash[+i]);
  }

  /* ---------------------------------------------------------------- blocks */
  const RE = {
    fence: /^( {0,3})(`{3,}|~{3,})[ \t]*([^\s`]*)[^`]*$/,
    heading: /^ {0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$/,
    hr: /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/,
    quote: /^ {0,3}>[ \t]?(.*)$/,
    ul: /^( *)([-*+])([ \t]+)(.*)$/,
    ol: /^( *)(\d{1,9})([.)])([ \t]+)(.*)$/,
    tableSep: /^ *\|?[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)*\|? *$/,
  };

  const indentOf = (l) => l.length - l.trimStart().length;

  function itemMatch(line) {
    let m = RE.ul.exec(line);
    if (m && !RE.hr.test(line)) {
      return { ordered: false, indent: m[1].length, offset: m[1].length + 1 + Math.min(m[3].length, 4), rest: m[4], num: 1 };
    }
    m = RE.ol.exec(line);
    if (m) {
      return { ordered: true, indent: m[1].length, offset: m[1].length + m[2].length + 1 + Math.min(m[4].length, 4), rest: m[5], num: parseInt(m[2], 10) };
    }
    return null;
  }

  const splitRow = (line) => {
    let t = line.trim();
    if (t.startsWith('|')) t = t.slice(1);
    if (t.endsWith('|') && !t.endsWith('\\|')) t = t.slice(0, -1);
    const cells = [];
    let cur = '';
    for (let k = 0; k < t.length; k++) {                      // split on unescaped pipes (no regex lookbehind: old Safari)
      if (t[k] === '\\' && t[k + 1] === '|') { cur += '|'; k++; }
      else if (t[k] === '|') { cells.push(cur.trim()); cur = ''; }
      else cur += t[k];
    }
    cells.push(cur.trim());
    return cells;
  };

  function isTableStart(lines, i) {
    const head = lines[i], sep = lines[i + 1];
    return i + 1 < lines.length && head.includes('|') && sep.includes('|') && sep.includes('-') && RE.tableSep.test(sep)
      && splitRow(head).length >= 1;
  }

  function startsBlock(lines, i) {
    const l = lines[i];
    return RE.fence.test(l) || RE.heading.test(l) || RE.hr.test(l) || RE.quote.test(l) || !!itemMatch(l) || isTableStart(lines, i);
  }

  function codeBlock(lang, code) {
    const safeLang = /^[\w+#.\-]{1,24}$/.test(lang || '') ? lang : '';
    return '<div class="md-code"><div class="md-code-bar"><span class="md-lang">' + escapeHtml(safeLang || 'text') +
      '</span><button type="button" class="md-copy" data-md-copy aria-label="Copy code">Copy</button></div>' +
      '<pre><code>' + escapeHtml(code) + '</code></pre></div>';
  }

  function parseList(lines, start) {
    const first = itemMatch(lines[start]);
    const ordered = first.ordered, baseIndent = first.indent;
    const items = [];
    let i = start;

    while (i < lines.length) {
      const m = itemMatch(lines[i]);
      if (!m || m.ordered !== ordered || m.indent >= baseIndent + 2 || m.indent < baseIndent) break;

      const body = [m.rest];
      let j = i + 1;
      while (j < lines.length) {
        const line = lines[j];
        if (!line.trim()) {                                   // blank: belongs to the item only if more indented content follows
          let k = j + 1;
          while (k < lines.length && !lines[k].trim()) k++;
          if (k < lines.length && indentOf(lines[k]) >= m.indent + 2) { body.push(''); j++; continue; }
          break;
        }
        if (indentOf(line) >= m.indent + 2) { body.push(line.slice(Math.min(indentOf(line), m.offset))); j++; continue; }
        const sib = itemMatch(line);
        if (sib && sib.indent < m.indent + 2) break;          // next sibling (or a different list)
        if (RE.fence.test(line) || RE.heading.test(line) || RE.hr.test(line) || RE.quote.test(line)) break;
        if (body[body.length - 1].trim()) { body.push(line); j++; continue; }   // lazy continuation
        break;
      }

      let task = null;
      const t = /^\[([ xX])\][ \t]+([\s\S]*)$/.exec(body[0]);
      if (t) { task = t[1] !== ' '; body[0] = t[2]; }
      items.push({ body, task, num: m.num });
      i = j;
      while (i < lines.length && !lines[i].trim()) {          // blank lines between siblings
        let k = i; while (k < lines.length && !lines[k].trim()) k++;
        const nxt = k < lines.length ? itemMatch(lines[k]) : null;
        if (nxt && nxt.ordered === ordered && nxt.indent < baseIndent + 2 && nxt.indent >= baseIndent) { i = k; } else break;
      }
    }

    const tag = ordered ? 'ol' : 'ul';
    const startAttr = ordered && items[0].num !== 1 ? ` start="${items[0].num}"` : '';
    const lis = items.map((it) => {
      const kids = blocks(it.body);
      // tight item: unwrap the first paragraph when nothing but nested lists follows it
      const tight = kids.length > 0 && kids[0].t === 'p' && kids.slice(1).every((b) => b.t === 'list');
      const inner = tight ? kids[0].inner + kids.slice(1).map((b) => b.html).join('') : kids.map((b) => b.html).join('');
      const box = it.task === null ? '' :
        `<input type="checkbox" disabled ${it.task ? 'checked ' : ''}aria-label="${it.task ? 'done' : 'not done'}"> `;
      return `<li${it.task === null ? '' : ' class="md-task"'}>${box}${inner}</li>`;
    }).join('');
    return { html: `<${tag}${startAttr}>${lis}</${tag}>`, next: i };
  }

  function blocks(lines) {
    const out = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      let m;

      if ((m = RE.fence.exec(line))) {
        const indent = m[1].length, mark = m[2], lang = m[3];
        const closer = new RegExp('^ {0,3}' + (mark[0] === '`' ? '`' : '~') + '{' + mark.length + ',}[ \\t]*$');
        const code = [];
        i++;
        while (i < lines.length && !closer.test(lines[i])) {
          code.push(lines[i].slice(Math.min(indent, indentOf(lines[i]))));
          i++;
        }
        i++;                                                  // skip the closing fence (or run past the end while streaming)
        out.push({ t: 'code', html: codeBlock(lang, code.join('\n')) });
      } else if ((m = RE.heading.exec(line))) {
        const n = m[1].length;
        out.push({ t: 'h', html: `<div class="md-h md-h${n}" role="heading" aria-level="${Math.min(6, n + 2)}">${inline(m[2].trim())}</div>` });
        i++;
      } else if (RE.hr.test(line)) {
        out.push({ t: 'hr', html: '<hr>' });
        i++;
      } else if (RE.quote.test(line)) {
        const inner = [];
        while (i < lines.length && RE.quote.test(lines[i])) { inner.push(RE.quote.exec(lines[i])[1]); i++; }
        out.push({ t: 'quote', html: '<blockquote>' + blocks(inner).map((b) => b.html).join('') + '</blockquote>' });
      } else if (isTableStart(lines, i)) {
        const head = splitRow(lines[i]);
        const aligns = splitRow(lines[i + 1]).map((c) => (c.startsWith(':') && c.endsWith(':') ? 'a-center' : c.endsWith(':') ? 'a-right' : ''));
        const cell = (tag, text, k) => `<${tag}${aligns[k] ? ` class="${aligns[k]}"` : ''}>${inline(text || '')}</${tag}>`;
        const rows = [];
        i += 2;
        while (i < lines.length && lines[i].trim() && lines[i].includes('|') && !RE.fence.test(lines[i])) {
          const cells = splitRow(lines[i]);
          rows.push('<tr>' + head.map((_, k) => cell('td', cells[k], k)).join('') + '</tr>');
          i++;
        }
        out.push({
          t: 'table',
          html: '<div class="md-table"><table><thead><tr>' + head.map((h, k) => cell('th', h, k)).join('') +
            '</tr></thead><tbody>' + rows.join('') + '</tbody></table></div>',
        });
      } else if (itemMatch(line)) {
        const r = parseList(lines, i);
        out.push({ t: 'list', html: r.html });
        i = r.next;
      } else {
        const para = [line.trimEnd()];
        i++;
        while (i < lines.length && lines[i].trim() && !startsBlock(lines, i)) { para.push(lines[i].trimEnd()); i++; }
        const innerHtml = inline(para.join('\n'));
        out.push({ t: 'p', inner: innerHtml, html: `<p>${innerHtml}</p>` });
      }
    }
    return out;
  }

  function render(src) {
    const lines = String(src == null ? '' : src).replace(/\r\n?/g, '\n').replace(/\t/g, '    ').split('\n');
    return blocks(lines).map((b) => b.html).join('');
  }

  return { render, inline, escapeHtml, safeUrl };
});
