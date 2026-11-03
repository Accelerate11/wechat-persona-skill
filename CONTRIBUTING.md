# Contributing

请先用离线演示和虚构输入复现。补丁应包含与行为变化相关的测试，不提交任何真实聊天或人物成品。

```sh
python -m pip install -r requirements.txt
python -B -m unittest discover -s tests -p "test_*.py"
node --test tests/runtime.test.mjs
python scripts/demo.py
python scripts/check_public.py
```

修改源读取时，需要覆盖页面认证失败、WAL未提交尾部、分片发送者编号和账号核对；不得为了兼容而忽略校验或保存原始读取密钥。

修改人物提取时，需要保持完整会话验证集隔离、凭证脱敏、目标人物发言归属和证据ID核对。模型复核不构成人工真值，也不应宣传人格诊断或精确复制能力。

修改运行模块时，需要验证其他人/群聊无法读取私人资料，以及不同人格的新对话记忆不混用。修改安装器应保持计划预览、配置备份及默认不发送。

提交前检查`git diff --cached`；`check_public.py`只检查已跟踪文件，不能代替人工审阅。遵循现有Apache-2.0许可证并保留第三方归属。
