import test from 'node:test'
import assert from 'node:assert/strict'
import { allowed, contextFor, rank } from '../aurabot-module/index.mjs'

const bundle = {
  profile: { owner_qq: '123', source_cutoff: '2026-11-03' },
  memories: [
    { id: 'a', text: '原型人物曾讨论用Coffee手冲与温控。', visibility: 'owner_private', evidence_ids: ['m1'], source: 'original_wechat' },
    { id: 'b', text: '原型人物曾讨论盆栽和浇水。', visibility: 'owner_private', evidence_ids: ['m2'], source: 'original_wechat' },
  ], examples: [],
}

test('历史私人资料不会进入其他私聊、群聊或缺少身份的会话', () => {
  for (const chat of [{ kind: 'private', userId: '456' }, { kind: 'group', userId: '123' }, undefined]) {
    assert.equal(allowed(chat, '123'), false)
    assert.deepEqual(contextFor(bundle, chat, 'Coffee'), { text: '', memories: [], examples: [], episodes: [] })
  }
})

test('相关事实命中，未提供的事件没有虚构的回忆兜底', () => {
  const chat = { kind: 'private', userId: '123' }
  assert.equal(contextFor(bundle, chat, '之前聊的Coffee和温控').memories[0].id, 'a')
  assert.equal(contextFor(bundle, chat, '我们去年在火星参加婚礼').memories.length, 0)
  assert.equal(contextFor(bundle, chat, '你还记得我们之前那个什么').memories.length, 0)
})

test('检索不会把未批准可见范围的条目交给当前用户', () => {
  const unsafe = { ...bundle, memories: [{ id: 'x', text: 'Coffee confidential', visibility: 'other_person_private' }] }
  assert.equal(contextFor(unsafe, { kind: 'private', userId: '123' }, 'Coffee').memories.length, 0)
})

test('具体技术名不会被含“的事吗”的无关片段挤掉', () => {
  const items = [{ id: 'topic', text: 'Coffee水温要注意' }, { id: 'unrelated', text: '某某是那个地方的事吗' }]
  const hits = rank('之前聊Coffee的事吗', items)
  assert.deepEqual(hits.map(h => h.id), ['topic'])
})

test('单条记忆可命中，空身份不会获得私人资料', () => {
  assert.equal(rank('Coffee', [{ id: 'one', text: '喜欢手冲Coffee' }])[0].id, 'one')
  assert.equal(allowed({ kind: 'private', userId: '' }, ''), false)
  assert.equal(allowed({ kind: 'private', userId: '123' }, undefined), false)
})

test('后续省略问题借助真实多轮线索，新主题不会被旧主题顶替', () => {
  const chat = { kind: 'private', userId: '123' }
  const history = [{ role: 'user', text: 'Coffee温控' }, { role: 'assistant', text: '先说水温' }, { role: 'user', text: '嗯' }]
  assert.equal(contextFor(bundle, chat, '那后来呢', [], { recentMessages: history }).memories[0].id, 'a')
  const newTopic = contextFor(bundle, chat, '盆栽浇水', [], { recentMessages: history })
  assert.equal(newTopic.memories[0].id, 'b')
  assert.ok(!newTopic.memories.some(m => m.id === 'a'))
})

test('大条目不挤破上下文预算，保留的来源记录仍是完整JSON', () => {
  const large = { ...bundle, memories: Array.from({ length: 20 }, (_, i) => ({ id: 'fact-' + i,
    text: 'Coffee温控' + '说明'.repeat(2000), visibility: 'owner_private', evidence_ids: ['source-' + i] })) }
  const result = contextFor(large, { kind: 'private', userId: '123' }, 'Coffee', [], { maxCharacters: 600 })
  assert.ok(Array.from(result.text).length <= 600)
  assert.equal(result.memories.length, 0)
})
