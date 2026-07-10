export const meta = {
  name: 'legion-specialists-dispatch',
  description: 'Fan out Tier-3 specialists in parallel based on detected workspace frameworks',
  phases: [
    { title: 'Discover',  detail: 'Read workspace-discovery.json and scorecard to select specialists' },
    { title: 'Dispatch',  detail: 'Parallel specialist agents, one per detected framework domain' },
    { title: 'Reduce',    detail: 'Merge findings and write specialist-results.json' },
  ],
}

const SPECIALIST_RESULT_SCHEMA = {
  type: 'object',
  properties: {
    specialist: { type: 'string' },
    domain:     { type: 'string' },
    findings:   { type: 'array', items: { type: 'string' } },
    passed:     { type: 'boolean' },
  },
  required: ['specialist', 'domain', 'findings', 'passed'],
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
const TIER_ORDER = ['cheap', 'standard', 'strong', 'ultra']

// A valid passed:false is a real finding, not a failure — only a null/FAILED result is retried.
async function agentTiered(prompt, opts, tier) {
  const idx = TIER_ORDER.indexOf(tier)
  const res = await agent(prompt, { ...opts, ...TIER[tier] })
  const failed = !res || (typeof res === 'string' && res.includes('FAILED'))
  if (failed && idx >= 0 && idx < TIER_ORDER.length - 1) {
    log(`agent ${opts.label || ''} unusable at ${tier} — retrying at ${TIER_ORDER[idx + 1]}.`)
    return await agent(prompt, { ...opts, ...TIER[TIER_ORDER[idx + 1]] })
  }
  return res
}

// The runtime has no Node APIs; offload to an agent()'s Bash tool, which returns only a condensed
// result. Plain cheap agent: a shell failure is a graceful-degrade signal, not worth retrying up.
{
  const spineResult = await agent(
    'Compile the prompt-cache prefix, then return ONLY a one-line status.\n'
    + 'Use whichever Python launcher exists (try `python`, then `python3`):\n'
    + '  python tools/corporate_spine_compiler.py --compile\n'
    + 'Return only the last line of stdout. If it exits non-zero or errors, reply exactly FAILED.',
    { label: 'spine-compile', ...TIER.cheap }
  )
  if (!spineResult || String(spineResult).includes('FAILED')) {
    log('Warning: spine compile failed, proceeding with stale cache.')
  }
}

phase('Discover')

const DISCOVERY_SCHEMA = {
  type: 'object',
  properties: {
    frameworks:   { type: 'array', items: { type: 'string' } },
    task_id:      { type: 'string' },
  },
  required: ['frameworks', 'task_id'],
}

const context = await agent(
  'Read .claude/state/workspace-discovery.json. '
  + 'From the first project entry, extract the frameworks array (whatever it contains — '
  + 'do not assume any specific framework). '
  + 'Return: frameworks (array of the framework/library names discovered), '
  + 'task_id ("legion_specialists_" + the first framework name or "code").',
  { label: 'discover-frameworks', schema: DISCOVERY_SCHEMA }
)

if (!context) {
  log('Workspace discovery unavailable — skipping specialist dispatch.')
  return { status: 'skipped', reason: 'workspace-discovery.json not readable' }
}

log(`Frameworks detected: ${context.frameworks.join(', ') || 'none'}`)

phase('Dispatch')

const specialistDefs = []

const seen = new Set()
for (const fw of context.frameworks || []) {
  const name = String(fw || '').trim()
  if (!name || seen.has(name)) continue
  seen.add(name)
  specialistDefs.push({
    name: `${name}-specialist`,
    domain: name,
    tier: 'standard',
    prompt:
      `You are the ${name} specialist for this workspace. `
      + `Inspect .claude/state/workspace-discovery.json and the discovered files that use ${name}. `
      + `Learn how ${name} is used here from the code itself, then report up to 5 concrete `
      + `correctness, performance, or misconfiguration risks specific to this usage. `
      + `Return findings as an array of short strings, and passed=true if no critical issues.`,
  })
}

specialistDefs.push({
  name: 'test-validation-runner',
  domain: 'validation',
  tier: 'cheap',
  prompt:
    'You are the validation runner. '
    + 'Read .claude/state/tier-decision.json if it exists. '
    + 'Report the board tier and any contested principles. '
    + 'Return findings as an array of short strings, and passed=true if tier >= 1.',
})

const makeSpecThunk = (spec) => () =>
  agentTiered(spec.prompt, {
    label: `specialist:${spec.name}`,
    phase: 'Dispatch',
    schema: SPECIALIST_RESULT_SCHEMA,
  }, spec.tier || 'standard').then(r =>
    (r && typeof r === 'object') ? { ...r, specialist: spec.name, domain: spec.domain } : null
  )

log(`Dispatching ${specialistDefs.length} specialist(s) (max ${MAX_PARALLEL} concurrent).`)
const specialistResults = await boundedParallel(specialistDefs, MAX_PARALLEL, makeSpecThunk)

phase('Reduce')

const valid = (specialistResults || []).filter(Boolean)
const allPassed = valid.every(r => r.passed)

const summary = await agent(
  `Write the following JSON to .claude/state/specialist-results.json:\n`
  + JSON.stringify({
    task_id: context.task_id,
    all_passed: allPassed,
    specialists: valid,
  }, null, 2),
  { label: 'write-specialist-results' }
)

log(`Specialist dispatch complete. ${valid.length}/${specialistDefs.length} responded. all_passed=${allPassed}`)

return {
  status: allPassed ? 'pass' : 'needs_fix',
  task_id: context.task_id,
  specialists_deployed: valid.length,
  frameworks_targeted: context.frameworks,
  all_passed: allPassed,
}
