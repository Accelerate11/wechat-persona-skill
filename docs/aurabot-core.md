# Aurabot 本体改进

人物扩展可以直接用于原版Aurabot；本体补丁额外增强整个聊天中枢的对话原话记忆，参考实现对应上游提交 `b3301f6b014016e141c07d266a716c0fea566aab`（1.1.24）。它不是对未知版本通用的替换包。

补丁位于 `integrations/aurabot-memory.patch`。在独立Aurabot源码工作区检查并应用：

```sh
git apply --check /path/to/wechat-persona-skill/integrations/aurabot-memory.patch
git apply /path/to/wechat-persona-skill/integrations/aurabot-memory.patch
node --test test/conversation-context.test.js test/memory.test.js test/e2e.test.js
```

新增的 `src/chat/conversation-context.js` 与本仓库 `aurabot-module/conversation.mjs` 使用相同实现，采用MIT许可。修改核心后的部署应备份原文件并重载插件核心；扩展模块的热重载不能替代核心重载。安装器仍默认禁用发送，部署期间不要把测试请求发到真实QQ。

本体会把QQ原始用户消息与完成轮次的assistant回复按人格和聊天分别保留，重启后可检索较早片段；群聊保留每个实际发言人的标识。消息引用只是资料，不变成一条新指令。近期多轮线索用于指代，明确新主题优先。预算只约束注入的记忆片段；完整模型窗口仍由DSH宿主管理。

事实检索新增聊天范围过滤；近似但含否定的句子不会自动去重合并，重复观察也不把旧事件改成今天发生的事。旧无范围记忆保留原共享行为，迁移时需审查，不能保证旧条目已自动私有化。

原版也会记录聊天流水，但每日整理可能清理旧流水；新追加日志独立保存，不把模型总结当唯一真相。机器人自己说过的话只证明它曾这样回答，不能证明原型经历或用户事实。

研究与评估限制见 [研究笔记](research.md)。完整上游测试包含依赖本地当前时间的桌宠测试；应记录测试时区，并用未修改上游在相同时区对照失败，避免把无关失败误报成本补丁通过或失败。
