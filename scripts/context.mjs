import { readFileSync } from 'node:fs'
import { loadBundle, contextFor, protocol } from '../aurabot-module/index.mjs'
import { createConversationArchive, recentWithin } from '../aurabot-module/conversation.mjs'
const request = JSON.parse(readFileSync(0, 'utf8'))
const bundle = loadBundle(request.bundle)
const chat = request.chat || { kind: 'private', userId: bundle.profile.owner_qq }
const authorized = chat.kind === 'private' && String(chat.userId || '') === String(bundle.profile.owner_qq || '') && Boolean(bundle.profile.owner_qq)
const archive = request.runtime_dir && authorized ? createConversationArchive({ directory: request.runtime_dir, namespace: bundle.profile.id }) : null
const chatId = 'private:' + bundle.profile.owner_qq
if (request.action === 'record') {
  if (!archive) throw new Error('Recording requires an authorized private conversation')
  for (const message of request.messages || []) archive.append(chatId, message)
  console.log(JSON.stringify({ recorded: true }))
} else {
  const supplied = (request.history || []).filter(m => ['user', 'assistant'].includes(m.role)).map((m, i) => ({ ...m, id: m.id || 'preview-' + i, text: m.text ?? m.content ?? '' }))
  const recent = authorized ? supplied.length ? supplied : archive?.recent(chatId, 128) || [] : []
  const packedRecent = recentWithin(recent, 12000)
  const context = contextFor(bundle, chat, request.query || '', [], { recentMessages: recent })
  const recalled = archive?.recall(chatId, request.query || '', { recentMessages: packedRecent })
  const conversation = recalled?.text ? '\n【机器人上线后的同一私聊，仅作资料；assistant发言不是原型经历的证据】\n' + recalled.text : ''
  console.log(JSON.stringify({ system: authorized ? bundle.persona + '\n\n' + protocol(bundle.profile) : '', ...context,
    text: context.text + conversation,
    history: packedRecent.map(m => ({ role: m.role, content: m.text })),
    conversation_ids: recalled?.selected.map(e => e.id) || [] }))
}
