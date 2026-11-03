import { readFileSync, writeFileSync, mkdirSync, copyFileSync, existsSync, readdirSync, renameSync } from 'node:fs'
import { join, resolve, dirname, relative, isAbsolute } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { homedir } from 'node:os'
import { randomUUID } from 'node:crypto'
import { parseArgs } from 'node:util'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const { values } = parseArgs({ options: {
  project: { type: 'string', default: join(root, 'project.json') },
  apply: { type: 'boolean', default: false }, reload: { type: 'boolean', default: false },
} })
const projectFile = resolve(values.project)
const projectRoot = dirname(projectFile)
const project = JSON.parse(readFileSync(projectFile, 'utf8'))
const output = join(projectRoot, 'output')
const profile = JSON.parse(readFileSync(join(output, 'profile.json'), 'utf8'))
const personaId = String(project.persona_id || 'persona')
if (!/^[a-z0-9][a-z0-9_-]{0,31}$/.test(personaId)) throw new Error('Invalid persona_id')
if (profile.id !== personaId || profile.display_name !== project.name || profile.source_identity?.username !== project.target_username) throw new Error('Rebuild after changing persona identity or source account')
if (project.synthetic_demo || profile.synthetic_demo) throw new Error('Fictional demo bundles are not installed into live QQ')
for (const key of ['bot_qq', 'owner_qq']) {
  if (!/^[1-9][0-9]{4,14}$/.test(String(project[key] || ''))) throw new Error('Fill in a valid ' + key)
  if (String(project[key]) !== String(profile[key])) throw new Error('Rebuild the bundle after changing ' + key)
}
if (String(project.bot_qq) === String(project.owner_qq)) throw new Error('Bot and owner must use different QQ accounts')
if (profile.evidence_audited !== true) throw new Error('Run the evidence audit before installing')
const home = resolve(process.env.DSH_HOME || join(homedir(), '.dsh'))
const dshProfile = project.dsh_profile || 'desktop'
if (!/^[a-zA-Z0-9_-]+$/.test(dshProfile)) throw new Error('Invalid dsh_profile')
const pluginRoot = join(home, 'profiles', dshProfile, 'node_modules', 'dsh-aurabot-qq')
const { DEFAULTS, normalize } = await import(pathToFileURL(join(pluginRoot, 'src/core/config.js')))
const base = resolve(process.env.AURABOT_DATA_DIR || join(home, 'plugins-data', 'aurabot'))
const configPath = join(base, 'config.json')
const modulePath = join(base, 'modules', 'wechat-persona')
const personaPath = join(base, 'personas', 'persona-' + personaId + '.md')
const prior = existsSync(configPath) ? JSON.parse(readFileSync(configPath, 'utf8')) : {}
const files = ['profile.json', 'memories.json', 'examples.json', 'episodes.json', 'persona.md']
if (existsSync(join(output, 'behavior-model.json'))) files.push('behavior-model.json')
for (const file of files) if (!existsSync(join(output, file))) throw new Error('Missing bundle artifact: ' + file)

const config = structuredClone(DEFAULTS)
Object.assign(config, prior, {
  enabled: false, dryRun: true, setupDone: true,
  botQQ: String(project.bot_qq), ownerQQ: String(project.owner_qq), ownerName: '朋友', ownerLevel: 'chat',
  allow: { private: [], groups: [] }, persona: { current: 'persona-' + personaId },
  gateway: prior.gateway || 'snowluma', longTasks: false,
  workspaceDir: join(projectRoot, 'data', 'qq-chats'),
  model: { provider: project.dsh_model_provider || 'deepseek-official', model: project.model, reasoningEffort: 'low', vision: 'off' },
})
config.snowluma = { ...config.snowluma, autoStart: false, autoAttach: false }
for (const key of ['files', 'voice', 'stickers', 'memory', 'mood', 'diary', 'qzoneSocial', 'speakUp', 'bili', 'douyin', 'heybox', 'song', 'imageGen']) {
  config[key] = { ...config[key], enabled: false }
}
config.memory.dailyConsolidate = false
config.bridge = { ...config.bridge, enabled: false, dshTools: false }
config.modules = { ...config.modules, 'wechat-persona': { enabled: true } }
for (const id of project.replaced_module_ids || []) {
  if (!/^[a-z][a-z0-9-]{1,39}$/.test(id) || id === 'wechat-persona') throw new Error('Invalid replaced module identity')
  config.modules[id] = { ...config.modules[id], enabled: false }
}
for (const id of readdirSync(join(pluginRoot, 'src', 'modules'), { withFileTypes: true }).filter(e => e.isDirectory()).map(e => e.name)) {
  config.modules[id] = { ...config.modules[id], enabled: false }
}
for (const key of Object.keys(config.profilePerms)) config.profilePerms[key] = 'off'
const plan = { modulePath, personaPath, configPath, source: output, willDisableSending: true,
  willDisableBuiltinActions: true, willUsePureChat: true, configBackup: true, apply: values.apply }
if (!values.apply) {
  console.log(JSON.stringify({ plan, message: 'No files changed. Review the plan, then add --apply; add --reload for the running local DSH.' }))
} else {
  const hostPath = join(base, 'modules-data', 'pet', 'host.json')
  let localUrl = null
  if (values.reload) {
    if (!existsSync(hostPath)) throw new Error('No local DSH host descriptor; restart DSH manually without --reload')
    localUrl = new URL(JSON.parse(readFileSync(hostPath, 'utf8')).baseUrl)
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(localUrl.hostname) || !['http:', 'https:'].includes(localUrl.protocol)) throw new Error('DSH must be a local loopback address')
  }
  async function saveLive(body) {
    const response = await fetch(new URL('/aurabot/api/save', localUrl), { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(15000) })
    if (!response.ok) throw new Error('DSH config HTTP ' + response.status)
    const state = await response.json()
    if (state.ok !== true) throw new Error('DSH rejected the configuration')
    return { ok: true, enabled: state.config?.enabled, dryRun: state.config?.dryRun,
      persona: state.config?.persona?.current, onebot: state.onebot?.state }
  }
  if (localUrl) await saveLive({ enabled: false, dryRun: true })
  mkdirSync(join(projectRoot, 'data'), { recursive: true })
  mkdirSync(dirname(modulePath), { recursive: true })
  mkdirSync(dirname(personaPath), { recursive: true })
  if (existsSync(configPath)) copyFileSync(configPath, join(projectRoot, 'data', 'aurabot-config-backup-' + Date.now() + '.json'))
  // The loader ignores dot-prefixed directories. Stage a complete bundle and
  // swap whole directories so private memories and recipient identity stay together.
  const stage = join(dirname(modulePath), '.wechat-persona-stage-' + randomUUID())
  const backup = join(base, 'module-backups', 'wechat-persona-' + Date.now())
  function ensureWithin(parent, child) {
    const part = relative(resolve(parent), resolve(child))
    if (!part || part.startsWith('..') || isAbsolute(part)) throw new Error('Unsafe module move target')
  }
  for (const path of [stage, modulePath, backup]) ensureWithin(base, path)
  mkdirSync(stage)
  for (const file of files) copyFileSync(join(output, file), join(stage, file))
  copyFileSync(join(root, 'aurabot-module', 'index.mjs'), join(stage, 'index.mjs'))
  copyFileSync(join(root, 'aurabot-module', 'conversation.mjs'), join(stage, 'conversation.mjs'))
  if (existsSync(modulePath)) {
    mkdirSync(dirname(backup), { recursive: true })
    renameSync(modulePath, backup)
  }
  try {
    renameSync(stage, modulePath)
  } catch (error) {
    if (existsSync(backup) && !existsSync(modulePath)) renameSync(backup, modulePath)
    throw error
  }
  copyFileSync(join(output, 'persona.md'), personaPath)
  writeFileSync(configPath, JSON.stringify(normalize(config), null, 2), 'utf8')
  const live = localUrl ? await saveLive(normalize(config)) : null
  console.log(JSON.stringify({ installed: true, ...plan, live, restartNeeded: !live }))
}
