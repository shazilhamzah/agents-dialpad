'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { render, inline, safeUrl } = require(process.env.MD_PATH || '../../agents_dialpad/static/markdown.js');

const has = (html, ...needles) => needles.forEach((n) => assert.ok(html.includes(n), `expected ${JSON.stringify(n)} in:\n${html}`));
const lacks = (html, ...needles) => needles.forEach((n) => assert.ok(!html.includes(n), `did not expect ${JSON.stringify(n)} in:\n${html}`));

test('the reported bug: ### heading renders as a heading, not literal hashes', () => {
  const html = render('### 1. Heading Stacking Critique: VALID');
  has(html, 'class="md-h md-h3"', 'role="heading"', '1. Heading Stacking Critique: VALID');
  lacks(html, '###');
});

test('all heading levels, and # needs a space', () => {
  for (let n = 1; n <= 6; n++) has(render('#'.repeat(n) + ' Title'), `md-h${n}`);
  lacks(render('#hashtag'), 'md-h');
  has(render('## Closed ##'), '>Closed<');
});

test('inline formatting', () => {
  has(inline('**bold** and *italic* and ~~gone~~ and `code`'), '<strong>bold</strong>', '<em>italic</em>', '<del>gone</del>', '<code>code</code>');
  has(inline('***both***'), '<strong><em>both</em></strong>');
  has(inline('__bold__ and _it_'), '<strong>bold</strong>', '<em>it</em>');
  lacks(inline('snake_case_name and 2*3*4'), '<em>');
});

test('markdown inside code spans is left alone, and html is escaped', () => {
  const html = inline('`**not bold** <b>`');
  has(html, '<code>**not bold** &lt;b&gt;</code>');
});

test('backslash escapes', () => {
  const html = inline('\\*literal\\* and \\# and \\`tick\\`');
  has(html, '*literal*');
  lacks(html, '<em>', '<code>');
});

test('raw HTML is escaped everywhere', () => {
  const evil = '<script>alert(1)</script><img src=x onerror=alert(1)>';
  for (const md of [evil, `# ${evil}`, `- ${evil}`, `> ${evil}`, `| ${evil} |\n|---|\n| ${evil} |`, `**${evil}**`, `[${evil}](https://a.b)`]) {
    const html = render(md);
    lacks(html, '<script', '<img', 'onerror=alert(1)>');   // the dangerous tag opener must never survive unescaped
    has(html, '&lt;');
  }
});

test('only http(s) and mailto are linked', () => {
  has(render('[ok](https://example.com/a?b=1&c=2)'), 'href="https://example.com/a?b=1&amp;c=2"', 'rel="noopener noreferrer nofollow"', 'target="_blank"');
  has(render('[mail](mailto:a@b.co)'), 'href="mailto:a@b.co"');
  for (const bad of ['javascript:alert(1)', 'JaVaScRiPt:alert(1)', 'data:text/html,<script>1</script>', 'vbscript:x', '/relative', '//evil.com', 'java\tscript:alert(1)', 'java\nscript:alert(1)']) {
    const html = render(`[click](${bad})`);
    lacks(html, '<a ', 'href=');
  }
  assert.equal(safeUrl('javascript:alert(1)'), null);
  assert.equal(safeUrl(' https://x.y '), 'https://x.y');
});

test('images are never loaded', () => {
  const html = render('![tracking pixel](https://evil.example/p.png?d=SECRET)');
  lacks(html, '<img', 'src=');
  has(html, 'image: tracking pixel', 'href="https://evil.example/p.png?d=SECRET"');
});

test('bare urls and autolinks, trailing punctuation excluded', () => {
  const html = inline('See https://example.com/path. Also <https://a.dev/x> and (https://b.dev/y).');
  has(html, 'href="https://example.com/path"', 'href="https://a.dev/x"', 'href="https://b.dev/y"');
  has(html, '</a>.', '</a>).');
});

test('unordered, ordered and nested lists', () => {
  const html = render('- one\n- two\n  - nested a\n  - nested b\n- three\n\n1. first\n2. second\n3. third');
  has(html, '<ul><li>one</li><li>two<ul><li>nested a</li><li>nested b</li></ul></li><li>three</li></ul>');
  has(html, '<ol><li>first</li><li>second</li><li>third</li></ol>');
});

test('ordered list keeps its start number; list directly after a paragraph', () => {
  has(render('5. five\n6. six'), '<ol start="5">');
  const html = render('Here are steps:\n1. a\n2. b');
  has(html, '<p>Here are steps:</p>', '<ol><li>a</li><li>b</li></ol>');
});

test('list item with several paragraphs and a code block', () => {
  const html = render('1. Install\n\n   Then run it.\n\n   ```sh\n   npm i\n   ```\n2. Done');
  has(html, '<li><p>Install</p><p>Then run it.</p>', 'class="md-code"', 'npm i', '<li>Done</li>');
});

test('task lists', () => {
  const html = render('- [x] done\n- [ ] todo');
  has(html, 'class="md-task"', 'checked', 'disabled');
});

test('fenced code: language, escaping, no markdown inside', () => {
  const html = render('```js\nconst a = "<b>" && **x**;\n```');
  has(html, 'class="md-lang">js<', '&lt;b&gt;', '**x**', 'data-md-copy');
  lacks(html, '<strong>');
});

test('unclosed fence (streaming) still renders as code', () => {
  const html = render('Look:\n```python\nprint(1)\nprint(');
  has(html, '<p>Look:</p>', 'class="md-code"', 'print(1)');
});

test('tilde fences and longer fences containing shorter ones', () => {
  has(render('~~~\na\n~~~'), 'class="md-code"');
  const html = render('````md\n```\ninner\n```\n````');
  has(html, '```\ninner\n```');
});

test('weird language names cannot inject', () => {
  const html = render('```"><script>\ncode\n```');
  lacks(html, '<script');
});

test('GFM tables with alignment and inline formatting', () => {
  const html = render('| Name | Qty | Note |\n|:-----|----:|:----:|\n| **A** | 1 | `x` |\n| B | 22 | ok |');
  has(html, 'class="md-table"', '<th>Name</th>', '<th class="a-right">Qty</th>', '<th class="a-center">Note</th>', '<td><strong>A</strong></td>', '<td class="a-right">22</td>');
});

test('table without outer pipes, ragged rows, escaped pipe', () => {
  const html = render('a | b\n--|--\n1 | 2 | 3\nx \\| y');
  has(html, '<th>a</th><th>b</th>', '<td>1</td><td>2</td>', 'x | y');
});

test('a pipe in text is not a table; --- after text is a rule', () => {
  lacks(render('a | b | c'), '<table');
  has(render('text\n\n---\n\nmore'), '<hr>');
});

test('blockquotes, nested, with content', () => {
  const html = render('> quote **b**\n> still\n>\n> > inner');
  has(html, '<blockquote>', '<strong>b</strong>', '<blockquote><p>inner</p></blockquote>');
});

test('horizontal rules', () => {
  for (const hr of ['---', '***', '___', '- - -']) has(render(hr), '<hr>');
});

test('paragraphs: blank line splits, single newline is a line break', () => {
  assert.equal(render('a\nb\n\nc'), '<p>a<br>b</p><p>c</p>');
});

test('an LLM-style answer renders cleanly end to end', () => {
  const md = [
    '### 1. Heading Stacking Critique: VALID',
    '',
    'The critique is **correct**:',
    '',
    '- Stacked `h1`/`h2` hurt rhythm',
    '- Use one heading per section',
    '',
    '| Level | Size |',
    '|---|---|',
    '| H2 | 24px |',
    '',
    '```css',
    'h2 { margin-top: 1.5em }',
    '```',
  ].join('\n');
  const html = render(md);
  has(html, 'md-h3', '<strong>correct</strong>', '<ul>', '<table>', 'class="md-code"');
  lacks(html, '###', '**', '```', '|---|');
});

test('empty and non-string input', () => {
  assert.equal(render(''), '');
  assert.equal(render(null), '');
  assert.equal(render(undefined), '');
});

test('private-use marker characters in input cannot forge output', () => {
  const OPEN = String.fromCharCode(0xE000), CLOSE = String.fromCharCode(0xE001);   // the renderer's internal markers
  const html = inline(OPEN + '0' + CLOSE + ' and `x`');
  assert.ok(!html.includes(OPEN) && !html.includes(CLOSE));
});

test('large and adversarial input stays fast', () => {
  const cases = ['**a '.repeat(8000), '*a'.repeat(15000), '['.repeat(20000), '`'.repeat(30000), '| a '.repeat(6000) + '\n' + '|-'.repeat(6000),
    '- '.repeat(3000), '> '.repeat(3000) + 'x', '1. a\n'.repeat(5000), 'word '.repeat(40000)];
  for (const c of cases) {
    const t0 = process.hrtime.bigint();
    render(c);
    const ms = Number(process.hrtime.bigint() - t0) / 1e6;
    assert.ok(ms < 1500, `took ${ms.toFixed(0)}ms for input starting ${JSON.stringify(c.slice(0, 12))}`);
  }
});

