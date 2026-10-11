export const meta = {
  name: 'local-label-claude-check',
  description: 'Label items with the local decide model in one batch, have Claude re-answer low-confidence fields blind, then score',
  whenToUse: 'Bulk classification where a local model does the volume and Claude checks the fields it is unsure of. args: {items, out, gold?, repo?, threshold?, thresholds?, every?, check_batch?, concurrency?, target?}',
  phases: [
    { title: 'Label', detail: 'one soh decide --batch call, missing ids retried once' },
    { title: 'Check', detail: 'Claude re-answers selected fields blind, in batches' },
    { title: 'Score', detail: 'soh label-score over labels, checks and gold' },
  ],
}

const ITEMS = args.items
const OUT = args.out
const GOLD = args.gold || ''
const REPO = args.repo || '.'
const THRESHOLD = args.threshold ?? 0.9
const PER_FIELD = JSON.stringify(args.thresholds || {})
const EVERY = args.every ?? 10
const BATCH = args.check_batch || 10
const CONC = args.concurrency || 4
const TARGET = args.target ?? 0.95
if (!ITEMS || !OUT) throw new Error('args.items and args.out are required')

const LABELS = `${OUT}/labels.jsonl`
const TODO = `${OUT}/todo.jsonl`
const CHECKS = `${OUT}/checks.jsonl`
const soh = `cd '${REPO}' && uv run soh`

const RUN = {
  type: 'object',
  properties: {
    exit_code: { type: 'integer' },
    body: { type: 'object', additionalProperties: true },
    stderr_tail: { type: 'string' },
  },
  required: ['exit_code', 'body'],
}
const ANSWERS = {
  type: 'object',
  properties: {
    results: { type: 'array', items: { type: 'object', properties: {
      id: { type: 'string' },
      answers: { type: 'object', additionalProperties: true },
    }, required: ['id', 'answers'] } },
  },
  required: ['results'],
}

const runner = (cmd, label, phase) => agent(
  `Run exactly this one command with Bash and nothing else: ${cmd}\n` +
  'It prints one JSON object on stdout. Return exit_code, body = the "body" field of that JSON ' +
  '(or {} if there is none), and stderr_tail = the last 300 characters of any error output.',
  { label, phase, schema: RUN, model: 'haiku', effort: 'low' })

phase('Label')
const labelCmd = `mkdir -p '${OUT}' && ${soh} decide --batch '${ITEMS}' --out '${LABELS}' --concurrency ${CONC} --json`
let run = await runner(labelCmd, 'decide --batch', 'Label')
let missing = (run && run.body && run.body.missing) || null
if (!run || run.exit_code !== 0 || missing === null) log(`label run failed: ${run ? run.stderr_tail : 'no result'}`)
if (missing === null || missing.length) {
  log(`${missing ? missing.length : 'unknown'} ids without an answer; retrying once`)
  run = await runner(labelCmd, 'decide --batch (retry)', 'Label')
  missing = (run && run.body && run.body.missing) || null
}
if (missing === null) throw new Error('the label stage produced no result twice')
if (missing.length) log(`still missing after retry (${missing.length}): ${missing.join(', ')}`)
log(`labelled ${run.body.items - missing.length}/${run.body.items}`)

const sel = await runner(
  `${soh} label-select --items '${ITEMS}' --labels '${LABELS}' --out '${TODO}' --threshold ${THRESHOLD} --thresholds '${PER_FIELD}' --every ${EVERY} --json`,
  'label-select', 'Label')
const nTodo = (sel && sel.body && sel.body.items) || 0
log(`checking ${nTodo} items, ${(sel && sel.body && sel.body.fields) || 0} fields (threshold ${THRESHOLD}, every ${EVERY})`)

const askBlind = (lines, label) => agent(
  `Print lines ${lines} (1-based, inclusive) of ${TODO} with Bash, e.g. sed -n '${lines}p' '${TODO}'. ` +
  'Each line is a JSON item with id, question, context and schema. For each item, read the context and answer every field in its schema yourself, from the context alone. ' +
  'A boolean field is true exactly when its description holds; an enum field takes one of its choices. Use no tool other than Bash for reading that file. ' +
  'Return one result per item: id and answers {field: value}, with every field of its schema.',
  { label, phase: 'Check', schema: ANSWERS, model: 'sonnet' })

const ranges = []
for (let s = 1; s <= nTodo; s += BATCH) ranges.push([s, Math.min(nTodo, s + BATCH - 1)])

phase('Check')
const checked = await parallel(ranges.map(([a, b]) => async () => {
  let got = await askBlind(`${a},${b}`, `check ${a}-${b}`)
  let rows = (got && got.results) || []
  if (rows.length < b - a + 1) {
    log(`check ${a}-${b} returned ${rows.length}/${b - a + 1}; retrying once`)
    const again = await askBlind(`${a},${b}`, `check ${a}-${b} (retry)`)
    const more = (again && again.results) || []
    if (more.length > rows.length) rows = more
    if (rows.length < b - a + 1) log(`check ${a}-${b} still short: ${rows.length}/${b - a + 1}`)
  }
  return rows
}))
const checks = checked.filter(Boolean).flat()
log(`Claude answered ${checks.length}/${nTodo} selected items`)

phase('Score')
const jsonl = checks.map(r => JSON.stringify({ id: r.id, answers: r.answers })).join('\n')
const goldArg = GOLD ? ` --gold '${GOLD}'` : ''
const report = await agent(
  `With Bash, write the text between the markers verbatim to ${CHECKS} using a quoted heredoc (cat > '${CHECKS}' <<'JSONL' ... JSONL), then run: ` +
  `${soh} label-score --labels '${LABELS}' --checks '${CHECKS}'${goldArg} --target ${TARGET}\n` +
  'Return that command\'s stdout exactly, with nothing added.\n----- BEGIN -----\n' + jsonl + '\n----- END -----',
  { label: 'label-score', phase: 'Score', model: 'haiku', effort: 'low' })

return { labelled: run.body.items - missing.length, items: run.body.items, missing, checked: checks.length, selected: nTodo, report }
