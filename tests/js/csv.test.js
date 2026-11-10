'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const FilesUtil = require('../../agents_dialpad/static/files_util.js');

test('parseCSV handles basic comma-separated fields', () => {
  const csv = 'name,age,city\nAlice,30,New York\nBob,25,London';
  const rows = FilesUtil.parseCSV(csv);
  assert.equal(rows.length, 3);
  assert.deepEqual(rows[0], ['name', 'age', 'city']);
  assert.deepEqual(rows[1], ['Alice', '30', 'New York']);
  assert.deepEqual(rows[2], ['Bob', '25', 'London']);
});

test('parseCSV handles quoted fields and escaped quotes', () => {
  const csv = 'title,description\n"Book","A ""classic"" novel"\n"Movie","An adventure"';
  const rows = FilesUtil.parseCSV(csv);
  assert.equal(rows.length, 3);
  assert.deepEqual(rows[1], ['Book', 'A "classic" novel']);
});

test('parseCSV handles newlines inside quotes', () => {
  const csv = 'col1,col2\n"line 1\nline 2","normal"';
  const rows = FilesUtil.parseCSV(csv);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows[1], ['line 1\nline 2', 'normal']);
});

test('parseCSV sniffs semicolon delimiter', () => {
  const csv = 'name;age;city\r\nAlice;30;Paris\r\nBob;25;Berlin';
  const rows = FilesUtil.parseCSV(csv);
  assert.equal(rows.length, 3);
  assert.deepEqual(rows[1], ['Alice', '30', 'Paris']);
});

test('parseCSV handles ragged rows and trailing newlines', () => {
  const csv = 'a,b,c\n1,2\n3,4,5,6\n';
  const rows = FilesUtil.parseCSV(csv);
  assert.equal(rows.length, 3);
  assert.deepEqual(rows[0], ['a', 'b', 'c']);
  assert.deepEqual(rows[1], ['1', '2']);
  assert.deepEqual(rows[2], ['3', '4', '5', '6']);
});

test('parseCSV handles empty and whitespace input', () => {
  assert.deepEqual(FilesUtil.parseCSV(''), []);
  assert.deepEqual(FilesUtil.parseCSV('   \n  \n'), []);
});
