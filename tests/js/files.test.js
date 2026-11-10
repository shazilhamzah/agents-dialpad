'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const FilesUtil = require('../../agents_dialpad/static/files_util.js');

test('joinPath joins segments cleanly without double slashes', () => {
  assert.equal(FilesUtil.joinPath('', 'foo.txt'), 'foo.txt');
  assert.equal(FilesUtil.joinPath('src', 'foo.txt'), 'src/foo.txt');
  assert.equal(FilesUtil.joinPath('src/', 'foo.txt'), 'src/foo.txt');
  assert.equal(FilesUtil.joinPath('src/', '/foo.txt'), 'src/foo.txt');
  assert.equal(FilesUtil.joinPath('src/sub', 'foo.txt'), 'src/sub/foo.txt');
});

test('crumbs returns hierarchy from project root to target directory', () => {
  const rootCrumbs = FilesUtil.crumbs('my-proj', '');
  assert.deepEqual(rootCrumbs, [{ name: 'my-proj', path: '' }]);

  const subCrumbs = FilesUtil.crumbs('my-proj', 'src/components/button');
  assert.deepEqual(subCrumbs, [
    { name: 'my-proj', path: '' },
    { name: 'src', path: 'src' },
    { name: 'components', path: 'src/components' },
    { name: 'button', path: 'src/components/button' },
  ]);
});

test('humanSize formats byte sizes correctly', () => {
  assert.equal(FilesUtil.humanSize(0), '0 B');
  assert.equal(FilesUtil.humanSize(500), '500 B');
  assert.equal(FilesUtil.humanSize(1024), '1.0 KB');
  assert.equal(FilesUtil.humanSize(2048), '2.0 KB');
  assert.equal(FilesUtil.humanSize(10240), '10 KB');
  assert.equal(FilesUtil.humanSize(1048576), '1.0 MB');
});

test('ago formats timestamps relative to now', () => {
  const now = Date.now() / 1000;
  assert.equal(FilesUtil.ago(now - 10), 'just now');
  assert.equal(FilesUtil.ago(now - 120), '2m ago');
  assert.equal(FilesUtil.ago(now - 7200), '2h ago');
  assert.equal(FilesUtil.ago(now - 172800), '2d ago');
  assert.equal(FilesUtil.ago(null), '');
});

test('sniffDelimiter detects comma, semicolon, and tab', () => {
  assert.equal(FilesUtil.sniffDelimiter('a,b,c'), ',');
  assert.equal(FilesUtil.sniffDelimiter('a;b;c'), ';');
  assert.equal(FilesUtil.sniffDelimiter('a\tb\tc'), '\t');
  assert.equal(FilesUtil.sniffDelimiter('"a;b",c,d'), ',');
});

test('chunkLines divides arrays into bounded chunks', () => {
  const lines = Array.from({ length: 1250 }, (_, i) => `line ${i + 1}`);
  const chunks = FilesUtil.chunkLines(lines, 500);
  assert.equal(chunks.length, 3);
  assert.equal(chunks[0].length, 500);
  assert.equal(chunks[1].length, 500);
  assert.equal(chunks[2].length, 250);
});

