// Trim markdown that is still being written, so a streaming answer never shows raw markers:
//  - a table appears only once its header and separator lines have arrived, and a row only once
//    it is complete;
//  - bold, italic or code that has opened but not closed yet is held back until it closes.
// The finished answer is rendered without this.

const TABLE_LINE = /^\s*\|/
const TABLE_SEPARATOR = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/

export function trimPartialMarkdown(text) {
  if (!text) return text
  let lines = text.split('\n')
  const endsWithNewline = text.endsWith('\n')

  // Tables: the trailing run of table lines.
  let start = lines.length
  while (start > 0 && (TABLE_LINE.test(lines[start - 1]) || (start === lines.length && lines[start - 1] === '' && start > 1 && TABLE_LINE.test(lines[start - 2])))) {
    start--
  }
  const run = lines.slice(start).filter((l) => l !== '')
  if (run.length > 0) {
    if (run.length < 2 || !TABLE_SEPARATOR.test(run[1]) || (run.length === 2 && !endsWithNewline)) {
      lines = lines.slice(0, start) // header or separator not complete yet: hide the table
    } else if (!endsWithNewline && !run[run.length - 1].trim().endsWith('|')) {
      lines = lines.slice(0, lines.length - 1) // last row not complete yet
    }
  }

  // Inline emphasis/code on the last line: cut at the first marker that is still open.
  const last = lines.length - 1
  if (last >= 0) lines[last] = cutUnclosed(lines[last])
  return lines.join('\n')
}

function cutUnclosed(line) {
  const bullet = line.match(/^\s*(?:[*+-]|\d+\.)\s+/) // a list marker is not emphasis
  let i = bullet ? bullet[0].length : 0
  const open = { bold: -1, italic: -1, code: -1 }
  while (i < line.length) {
    if (line[i] === '\\') { i += 2; continue }
    if (line[i] === '`') {
      open.code = open.code < 0 ? i : -1
      i += 1
      continue
    }
    if (open.code >= 0) { i += 1; continue } // no emphasis inside code
    if (line.startsWith('**', i)) {
      open.bold = open.bold < 0 ? i : -1
      i += 2
      continue
    }
    if (line[i] === '*') {
      // "a * b" with spaces on both sides is a literal asterisk, not emphasis
      const literal = line[i - 1] === ' ' && (line[i + 1] === ' ' || i + 1 === line.length)
      if (!literal) open.italic = open.italic < 0 ? i : -1
    }
    i += 1
  }
  const cuts = Object.values(open).filter((p) => p >= 0)
  return cuts.length ? line.slice(0, Math.min(...cuts)) : line
}
