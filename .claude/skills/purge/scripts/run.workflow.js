export const meta = {
  name: 'purge',
  description: 'Bring every area of the repository into line with the house rules, many agents in parallel, one deploy at the end',
  whenToUse: 'Started by the /purge skill only',
  phases: [
    { title: 'Setup', detail: 'local branch purge-run off origin/main' },
    { title: 'Map', detail: 'duplicate finder first, then areas with disjoint files, scored against the rulebook' },
    { title: 'Shared', detail: 'one change per duplicate group: fold the copies into one function in its home' },
    { title: 'Wave', detail: 'per area: plan, change, refute, merge into purge-run' },
    { title: 'Suite', detail: 'one full-suite run per wave; a red reverts the merges that caused it' },
    { title: 'Retro', detail: 'every kind of break fixed more than once gets an automatic check' },
    { title: 'Deploy', detail: 'full suite on purge-run, one squashed commit to main' },
  ],
}

// args: { issue: <tracking issue number>, maxWaves: <int, default 6>, repo: <abs path of the repository root>,
//         hooks: <the `purge` object of the repository's .claude/project.json> }
// The script names no repository: every command and path that differs per repository comes in through `hooks`.
if (!args || !args.issue || !args.repo || !args.hooks) throw new Error('purge needs args.issue, args.repo and args.hooks (the purge key of .claude/project.json)')
const ISSUE = args.issue
const MAX_WAVES = args.maxWaves || 6
const REPO = args.repo
const H = args.hooks
const RUN = `${REPO}/.claude/worktrees/purge-run`
const EXTRA = (H.extra_checks || []).join(', ') || 'none'

const RULEBOOK = `You are part of a /purge run (skill .claude/skills/purge/SKILL.md in ${REPO}; read its "The rulebook" and "The registers every change respects" sections first, they bind you). In short: judge code only by (1) root CLAUDE.md Rules, (2) the module standard, bible chapter workflow/module-standard, and its auditor's conformance checklist where it has one, (3) the codebase-design skill's deep-module vocabulary. Keep behaviour: conforming is refactoring; the full suite at the end of each wave judges it. One test per level, one test function a file, inside its time: one test per module (and per module group where the repository has groups), the full suite on top; a test file holds ONE test function, within its time (${H.time_budget}). This repository's test bookkeeping: modules are ${H.modules}; ${H.test_debt} lists the level debt and the gaps; ${H.test_check} must agree with the tree; the debt lists (${H.debt_lists}) only ever shrink; a new test is born only this way: ${H.test_new}. Never edit paths in .claude/harness.lock, never change a module the module standard marks regulated (report it instead), never create a .md file or a GitHub issue, a test and its change in one commit, keep the word budgets the repository's rules set for docs and overlays. Use the code index root CLAUDE.md names (load its tools with ToolSearch) before grep. All work happens on the local branch purge-run (worktree ${RUN}); NEVER push anything; only the Deploy phase pushes. Write in the voice root CLAUDE.md sets.`

const AREA_SCHEMA = {
  type: 'object',
  properties: {
    areas: { type: 'array', items: { type: 'object', properties: {
      name: { type: 'string' },
      paths: { type: 'array', items: { type: 'string' }, description: 'directories this area owns exclusively' },
      breaks: { type: 'array', items: { type: 'string' }, description: 'checklist line number + one-line finding + file' },
      shares_hub_with: { type: 'array', items: { type: 'string' }, description: 'names of other areas that import the same hub file' },
      regulated: { type: 'boolean' },
    }, required: ['name', 'paths', 'breaks', 'shares_hub_with', 'regulated'] } },
  },
  required: ['areas'],
}
const PLAN_SCHEMA = {
  type: 'object',
  properties: { changes: { type: 'array', items: { type: 'object', properties: {
    title: { type: 'string' }, files: { type: 'array', items: { type: 'string' } }, rule: { type: 'string' }, how: { type: 'string' },
    value: { type: 'string', enum: ['high', 'low'], description: 'high: dead code out, a duplicate copy folded, extra tests folded, a missing test, a real depth or seam fix; low: a docstring sentence or a name or visibility change only' },
    docs_only: { type: 'boolean', description: 'true when the change touches only docstrings, comments or markdown' },
  }, required: ['title', 'files', 'rule', 'how', 'value', 'docs_only'] } } },
  required: ['changes'],
}
const VERDICT = { type: 'object', properties: { refuted: { type: 'boolean' }, why: { type: 'string' } }, required: ['refuted', 'why'] }
const MEMBER = { type: 'object', properties: {
  file: { type: 'string' }, line: { type: 'number' }, name: { type: 'string' }, module: { type: 'string' },
}, required: ['file', 'line', 'name', 'module'] }
const DUPLICATES_SCHEMA = {
  type: 'object',
  properties: {
    groups: { type: 'array', items: { type: 'object', properties: {
      kind: { type: 'string', enum: ['function', 'near', 'constant'] },
      language: { type: 'string', enum: ['python', 'ts'] },
      size: { type: 'number' },
      members: { type: 'array', items: MEMBER },
      home: { type: 'string' },
      deploy_boundary: { type: 'boolean' },
    }, required: ['kind', 'language', 'size', 'members', 'home', 'deploy_boundary'] } },
    counts: { type: 'object', properties: { function: { type: 'number' }, near: { type: 'number' }, constant: { type: 'number' } } },
  },
  required: ['groups'],
}

// The Workflow tool refuses a workflow's 1,000th agent, and a run that hits it never
// reaches its deploy. Every agent goes through runAgent so the script counts them;
// past AGENT_CAP no new change starts, the changes in flight finish, and the run goes
// straight to its suite, retro and deploy, which the headroom under 1,000 pays for.
const AGENT_CAP = 880
let agentsStarted = 0
let stoppedAtCap = false
function runAgent(prompt, opts) {
  agentsStarted++
  return agent(prompt, opts)
}
// True once the run must start nothing new; the first call logs it and notes it in the report.
function atAgentCap() {
  if (agentsStarted < AGENT_CAP) return false
  if (!stoppedAtCap) {
    stoppedAtCap = true
    log(`stopped early at the agent cap: ${agentsStarted} agents started, cap ${AGENT_CAP}; finishing changes in flight, then suite, retro and deploy`)
    report.push(`stopped early at the agent cap (${agentsStarted} agents started, cap ${AGENT_CAP})`)
  }
  return true
}

// The one life of a planned change: a worker makes it in its own worktree, reviewers
// try to refute it, a refuted change gets one repair, and a survivor is merged into
// purge-run. Returns true when the change was merged.
async function runChange(owner, change, slug, phaseName = 'Wave') {
  if (atAgentCap()) { report.push(`not started at the agent cap in ${owner}: ${change.title}`); return false }
  const work = await runAgent(`${RULEBOOK}\n\nMake this change for "${owner}": ${change.title}\nRule: ${change.rule}\nFiles: ${change.files.join(', ')}\nHow: ${change.how}\nWork in your own worktree off purge-run: cd ${REPO} && git worktree add .claude/worktrees/${slug} -b ${slug} purge-run && cd .claude/worktrees/${slug} && ${H.setup}. Do NOT run the test suite: the wave ends with one full-suite run that judges every change. Run ${H.test_check} when you touch a test, and see the break of a test you add or fold into turn it red once; commit once. Return the commit sha, or "dropped: <why>".`, { label: `work:${slug}`, phase: phaseName })
  if (!work || /^dropped/i.test(work)) { report.push(`dropped in ${owner}: ${change.title}`); return false }
  // A docs-only change cannot change what a caller sees, so it gets the rulebook lens alone.
  const lenses = ['the rulebook: does it really fix the break, minimally, without breaking another rule or register?']
  if (!change.docs_only) lenses.push('behaviour: does any caller now see something different, or is a test weakened?')
  const review = (round) => parallel(lenses.map((lens, li) => () =>
    runAgent(`${RULEBOOK}\n\nTry to refute this change on branch ${slug} (worktree ${REPO}/.claude/worktrees/${slug}), judged by ${lens} Worker said: ${work}\nDefault to refuted=true when unsure.`, { label: `refute:${slug}:${round}:${li}`, phase: phaseName, schema: VERDICT })))
  let votes = await review(0)
  let ok = votes.filter(Boolean).every(v => !v.refuted)
  if (!ok) {
    // One chance to repair: most refusals are a one-line slip, and throwing
    // the whole change away wasted the work that went into it.
    const reasons = votes.filter(Boolean).filter(v => v.refuted).map(v => v.why).join(' | ')
    const fixed = await runAgent(`${RULEBOOK}\n\nYour change on branch ${slug} (worktree ${REPO}/.claude/worktrees/${slug}) was refuted: ${reasons}\nFix exactly what the reviewers named, nothing else, and amend your commit. Return the new commit sha, or "dropped: <why>" when it cannot be fixed within the change.`, { label: `repair:${slug}`, phase: phaseName })
    if (fixed && !/^dropped/i.test(fixed)) {
      votes = await review(1)
      ok = votes.filter(Boolean).every(v => !v.refuted)
    }
  }
  const merge = await runAgent(`${RULEBOOK}\n\n${ok ? `Merge branch ${slug} into purge-run (cd ${RUN} && git merge --no-ff ${slug}); on a conflict, rebase ${slug} onto purge-run first.` : `Discard branch ${slug}: it was refuted (${votes.filter(Boolean).map(v => v.why).join(' | ')}).`} Then remove the worktree .claude/worktrees/${slug} and delete the branch. Return "merged" or "discarded".`, { label: `merge:${slug}`, phase: phaseName })
  if (merge && /merged/i.test(merge)) return true
  report.push(`refuted in ${owner}: ${change.title}`)
  return false
}

const groupFiles = group => [...new Set([...group.members.map(m => m.file), group.home])]
const groupLabel = group => `${group.kind} ${group.language} x${group.members.length} -> ${group.home}: ${group.members.map(m => `${m.file}:${m.line} ${m.name}`).join(', ')}`

phase('Setup')
await runAgent(`${RULEBOOK}\n\nSet up the run: cd ${REPO} && git fetch origin && (git worktree add ${RUN} -b purge-run origin/main || (cd ${RUN} && git checkout purge-run)) && cd ${RUN} && ${H.setup}. Confirm the test baseline on it: ${H.suite}, and ${H.test_check}. Return the baseline pass/fail counts; a red baseline is listed, not fixed.`, { label: 'setup', phase: 'Setup' })

const report = []
const reported = new Set()
// A group tried once (folded, dropped or refuted) is not offered again in a later wave.
const tried = new Set()
let dryWaves = 0
for (let wave = 1; wave <= MAX_WAVES && dryWaves < 2; wave++) {
  if (atAgentCap()) break
  phase('Map')
  // Areas are disjoint, so code that should be one function shared across areas is
  // never seen by any single lead. A deterministic finder looks across all of them first.
  // A repository without a duplicate finder skips the shared wave.
  const found = H.duplicates ? await runAgent(`${RULEBOOK}\n\nWave ${wave}: in ${RUN} run exactly: ${H.duplicates}. Return its JSON object unchanged (groups and counts). If the command fails, return {"groups": []} and nothing else.`, { label: `dup:w${wave}`, phase: 'Map', schema: DUPLICATES_SCHEMA }) : null
  const groups = (found && found.groups || []).filter(g => g.members && g.members.length > 1)
  groups.filter(g => g.deploy_boundary).forEach(g => {
    const line = `duplicate across deploy units, reported only: ${groupLabel(g)}`
    if (!reported.has(line)) { reported.add(line); report.push(line) }
  })
  // Fold groups whose files do not overlap this wave; an overlapping group waits for the next.
  const sharedFiles = new Set()
  const shared = []
  for (const group of groups.filter(g => !g.deploy_boundary && !tried.has(groupLabel(g)))) {
    const files = groupFiles(group)
    if (files.some(f => sharedFiles.has(f))) continue
    files.forEach(f => sharedFiles.add(f)); shared.push(group); tried.add(groupLabel(group))
  }
  const dupNote = groups.length
    ? `\n\nThe duplicate finder's groups (folded by the shared wave or reported, NOT area breaks; do not list them again):\n${groups.map(groupLabel).join('\n')}`
    : ''
  const map = await runAgent(`${RULEBOOK}\n\nWave ${wave}: map ${RUN}. Split the tracked tree into areas with disjoint paths: one per module as ${H.modules} defines a module, grouped where the index says files move together (its community rows where it has them, else shared importers). Skip vendored and third-party trees. For each area list every rulebook break you can verify (rule or checklist line, finding, file), using the index (hubs, importers), git log churn and open Issue rows touching it. Run ${H.test_debt} once and add its lines to the area that owns the path as breaks of two kinds: "fold: <module or group> has n extra tests (debt)" and "group test: <module group> has no test"; add every file of that area on a debt list (${H.debt_lists}) as "fold: <file> holds n test functions" or "fold: <file> takes n s". Return only areas with at least one break; mark regulated areas.${dupNote}`, { label: `map:w${wave}`, phase: 'Map', schema: AREA_SCHEMA })
  const broken = (map && map.areas || []).filter(a => a.breaks.length)
  const toFix = broken.filter(a => !a.regulated)
  broken.filter(a => a.regulated).forEach(a => report.push(`regulated, reported only: ${a.name}: ${a.breaks.length} breaks`))
  if (!toFix.length && !shared.length) { log(`wave ${wave}: no area breaks a rule and no duplicate to fold`); break }

  // Areas sharing a hub file go to different waves: take a set with no shared hubs this wave.
  const taken = new Set()
  const thisWave = []
  for (const area of toFix) {
    if (area.shares_hub_with.some(n => taken.has(n))) continue
    taken.add(area.name); thisWave.push(area)
  }
  log(`wave ${wave}: ${toFix.length} areas break rules, ${thisWave.length} run now`)

  // The shared wave runs first: one change per duplicate group, folded into its home.
  let sharedCount = 0
  if (shared.length) {
    phase('Shared')
    const results = await parallel(shared.map((group, gi) => () => runChange('shared', {
      title: `fold ${group.members.length} copies of ${group.members[0].name} into one ${group.kind === 'constant' ? 'constant' : 'function'} in ${group.home}`,
      files: groupFiles(group),
      rule: group.kind === 'constant'
        ? 'module standard: every constant has one home'
        : 'module standard: undeclared duplication is a split-brain finding',
      how: `Duplicate group from the finder (${group.kind}, ${group.language}, size ${group.size}): ${group.members.map(m => `${m.file}:${m.line} ${m.name} (module ${m.module})`).join('; ')}. Keep one copy in ${group.home} (create the function there if no member lives in it), delete the others, and update every caller of every copy to import the one (find them with the index: query_graph for callers, search_code for the name). Keep behaviour exactly: where the copies differ, the one must give each caller what its old copy gave, or the group is not a duplicate and you return "dropped: <the difference>". A constant group matches on name and value only: when the copies are independent settings that merely agree today (two timeouts for two different services, say), they are not one fact, so return "dropped: coincidental value". Keep each module's public interface: a module that exported its copy re-exports the one or its callers move.`,
      value: 'high',
      docs_only: false,
    }, `purge-shared-${wave}-${gi}`, 'Shared')))
    sharedCount = results.filter(Boolean).length
    report.push(`shared: ${sharedCount} of ${shared.length} duplicate groups folded`)
    log(`wave ${wave}: ${sharedCount} duplicate groups folded into purge-run`)
  }
  const sharedExclusion = sharedFiles.size
    ? `\nThe shared wave of this run folded duplicates in these files; do NOT touch them or their callers' import of them, and drop any break that names them: ${[...sharedFiles].join(', ')}`
    : ''

  phase('Wave')
  const merged = await pipeline(
    thisWave,
    area => atAgentCap() ? Promise.resolve({ area, plan: null }) : runAgent(`${RULEBOOK}\n\nYou lead area "${area.name}" (paths: ${area.paths.join(', ')}). Breaks found:\n${area.breaks.join('\n')}\nPlan the smallest set of changes that makes every break pass, each change small enough for one worker and one commit, touching only this area's paths (plus tests and register rows for them).${sharedExclusion} Order them so each leaves the tree green. Mark each change's value: high (dead code out, a duplicate copy folded, extra tests folded, a missing test, a real depth or seam fix) or low (a docstring sentence, or a name or visibility change and nothing else); mark docs_only when it touches only docstrings, comments or markdown. Plan the high-value changes first; the run skips low-value ones while an area still has high-value work. Two jobs besides the checklist ones: (fold) for a level with debt, or a file on a debt list (${H.debt_lists}), MERGE its checks into ONE test function of the answer that matters, never concatenate: keep the checks that pin real behaviour as cases of that one test (parametrize the same check over inputs), delete a check that repeats another or only reads the code's shape, keep the file within its time budget (${H.time_budget}), delete the folded files and their bookkeeping, delete or lower their debt entries, and keep the survivor's break red; (group test) for a module group with no test, add one born this way: ${H.test_new}, that drives the group's modules together through their public seams, with a proved break.`, { label: `lead:${area.name}`, phase: 'Wave', schema: PLAN_SCHEMA })
      .then(plan => ({ area, plan })),
    async ({ area, plan }) => {
      const done = []
      const planned = (plan && plan.changes || [])
      const high = planned.filter(change => change.value !== 'low')
      // Low-value changes (a docstring sentence, a name) cost as much review as a
      // real fix and buy little; they run only once an area has no high-value work.
      const chosen = high.length ? high : planned
      planned.filter(change => !chosen.includes(change)).forEach(change => report.push(`skipped as low value in ${area.name}: ${change.title}`))
      for (const [ci, change] of chosen.entries()) {
        const slug = `purge-${area.name.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}-${wave}-${ci}`
        if (await runChange(area.name, change, slug)) done.push(change.title)
      }
      return { area: area.name, merged: done }
    },
  )
  const count = sharedCount + merged.filter(Boolean).reduce((n, r) => n + r.merged.length, 0)
  merged.filter(Boolean).forEach(r => report.push(`${r.area}: ${r.merged.length} changes merged`))
  log(`wave ${wave}: ${count} changes merged into purge-run`)
  dryWaves = count ? 0 : dryWaves + 1

  if (count) {
    phase('Suite')
    const suite = await runAgent(`${RULEBOOK}\n\nWave ${wave} merged ${count} changes into purge-run. Run the full suite ONCE in ${RUN}: ${H.suite}, plus ${H.test_check}. Compare with the setup baseline. If something green at baseline is now red, find the merges of this wave that caused it by bisecting this wave's merge commits (git log --first-parent --merges on purge-run since the wave started; git bisect over them, re-running only the failing tests at each step), revert each culprit with git revert -m 1 <merge>, and re-run the full suite once to confirm green at baseline. Return "green" or "reverted: <merge subjects>".`, { label: `suite:w${wave}`, phase: 'Suite' })
    if (suite && /reverted/i.test(suite)) report.push(`wave ${wave} suite: ${suite}`)
  }
}

phase('Retro')
const retro = await runAgent(`${RULEBOOK}\n\nRetro on this run, following the retro skill (.claude/skills/retro/SKILL.md): the run's report is below. In ${RUN} on branch purge-run, for every KIND of break the run fixed in two or more places, classify it: mechanical (a fixed pattern: a file shape, an import, a name, a count) or judgement. For each mechanical kind build ONE deterministic check so it cannot come back: the cheapest of a rule in the repo's existing checks (its test check ${H.test_check}, an existing quality test, a pre-commit step in .claude/hooks/local/), any new test born this way: ${H.test_new}, with a proved break, and green on purge-run now. Never edit .claude/harness.lock paths (note shared-harness ideas for the harness source instead). Commit each check on purge-run. Judgement kinds and shared-harness ideas go in the returned list, not in code. Return: checks built (kind, where), judgement findings, shared-harness ideas.\n\nRun report:\n${report.join('\n')}`, { label: 'retro', phase: 'Retro' })

phase('Deploy')
const deploy = await runAgent(`${RULEBOOK}\n\nThis is the one deploy of the run. In ${RUN} on branch purge-run: run the full suite (${H.suite}), ${H.test_check}, and the extra checks (${EXTRA}). Compare with the setup baseline. For every new red: fix it on purge-run, or revert the merge that caused it (git revert -m 1 <merge>), until everything that was green at baseline is green. Then make one commit on top of origin/main holding the whole run: git fetch origin && git checkout -B purge-squash origin/main && git merge --squash purge-run && git commit -m "purge: <areas> follow the module standard and the house rules (#${ISSUE})" with a body listing the areas and the attribution trailer the session gives for commits. Push it as root CLAUDE.md says (rebase and re-run the selected tests on a race). Check the gate status of the sha once, the way root CLAUDE.md names. Remove the purge-run worktree and both local branches. Return the sha, the test counts before/after, and what was reverted.`, { label: 'deploy', phase: 'Deploy' })

return { report, retro, deploy }
