export const meta = {
  name: 'legion-companies-deliberation',
  description: 'Run parallel principle advocacy for contested scorecard entries',
  phases: [
    { title: 'Load Scorecard', detail: 'Read principle-scorecard.json and extract contested principles' },
    { title: 'Advocacy',       detail: 'Parallel T1 advocacy agents per contested principle' },
    { title: 'Conflict Set',   detail: 'Merge arguments into conflict-set.json for the Board' },
  ],
}

const SCORECARD_SCHEMA = {
  type: 'object',
  properties: {
    task_id:          { type: 'string' },
    is_contested:     { type: 'boolean' },
    contested_count:  { type: 'number' },
    arguments:        { type: 'array', items: { type: 'object' } },
  },
  required: ['task_id', 'is_contested', 'contested_count', 'arguments'],
}

const ADVOCACY_SCHEMA = {
  type: 'object',
  properties: {
    company:  { type: 'string' },
    argument: { type: 'string' },
  },
  required: ['company', 'argument'],
}

const MAX_PARALLEL = 6

function chunk(items, size) {
  const out = []
  for (let i = 0; i < items.length; i += Math.max(1, size)) out.push(items.slice(i, i + size))
  return out
}

// Use the runtime's parallel() (not a bare Promise.all) so its sub-agent scheduling/isolation holds.
async function boundedParallel(items, limit, makeThunk) {
  const results = []
  for (const batch of chunk(items, limit)) {
    const batchResults = await parallel(batch.map(makeThunk))
    for (const r of (batchResults || [])) results.push(r)
  }
  return results
}

const TIER = {
  cheap:    { model: 'claude-haiku-4-5-20251001', effort: 'low' },
  standard: { model: 'claude-sonnet-4-6',         effort: 'medium' },
  strong:   { model: 'claude-sonnet-4-6',         effort: 'high' },
  ultra:    { model: 'claude-opus-4-8',           effort: 'max' },
}

phase('Load Scorecard')

const scorecard = await agent(
  'Read .claude/state/principle-scorecard.json. ' +
  'Return: task_id, is_contested (true if conflicts array is non-empty), ' +
  'contested_count (number of contested_threshold: entries), ' +
  'and arguments as an empty array for now.',
  { label: 'load-scorecard', schema: SCORECARD_SCHEMA }
)

if (!scorecard || !scorecard.is_contested) {
  log('No contested principles — advocacy bypassed.')
  return { status: 'bypass', reason: 'All principle scores above threshold.' }
}

log(`${scorecard.contested_count} principle(s) contested — launching advocacy.`)

phase('Advocacy')

const PLAYBOOK_MAP = {
  simplicity:    'kiss-playbook.md',
  frugality:     'yagni-playbook.md',
  structure:     'solid-playbook.md',
  dryness:       'dry-playbook.md',
  decoupling:    'solid-playbook.md',
  encapsulation: 'solid-playbook.md',
  convention:    'kiss-playbook.md',
  craft:         'dry-playbook.md',
}

const contested = await agent(
  'Read .claude/state/principle-scorecard.json. ' +
  'Return only the principle names from conflicts entries that start with "contested_threshold:". ' +
  'Strip the prefix. Return as a JSON array of strings.',
  { label: 'extract-contested', schema: { type: 'array', items: { type: 'string' } } }
)

const principles = contested || []

const makeAdvocateThunk = (principle) => () =>
  agent(
    `You are the ${principle} Company advocate. ` +
    `Read .claude/skills/${PLAYBOOK_MAP[principle] || 'solid-playbook.md'} for your playbook. ` +
    `The principle "${principle}" is flagged as contested for task ${scorecard.task_id}. ` +
    `Draft a concise architectural argument (2-4 sentences) defending this principle ` +
    `and recommending the specific refactor needed to resolve the violation.`,
    { label: `advocate:${principle}`, phase: 'Advocacy', schema: ADVOCACY_SCHEMA, ...TIER.standard }
  )

log(`Advocating ${principles.length} contested principle(s) (max ${MAX_PARALLEL} concurrent).`)
const advocacyResults = await boundedParallel(principles, MAX_PARALLEL, makeAdvocateThunk)

phase('Conflict Set')

const validArguments = (advocacyResults || []).filter(Boolean)

const conflictSet = await agent(
  `Write the following JSON exactly to .claude/state/conflict-set.json:\n` +
  JSON.stringify({
    task_id: scorecard.task_id,
    is_contested: true,
    arguments: validArguments,
  }, null, 2),
  { label: 'write-conflict-set' }
)

log(`Advocacy complete. ${validArguments.length} argument(s) written to conflict-set.json.`)

return {
  status: 'completed',
  task_id: scorecard.task_id,
  deliberation_count: validArguments.length,
}
