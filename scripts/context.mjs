import { readFileSync } from 'node:fs'
import { loadBundle, contextFor, protocol } from '../aurabot-module/index.mjs'
const request = JSON.parse(readFileSync(0, 'utf8'))
const bundle = loadBundle(request.bundle)
const chat = request.chat || { kind: 'private', userId: bundle.profile.owner_qq }
const context = contextFor(bundle, chat, request.query || '')
console.log(JSON.stringify({ system: bundle.persona + '\n\n' + protocol(bundle.profile), ...context }))
