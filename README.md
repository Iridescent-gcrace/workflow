# AIWF (All-in-One Workflow Terminal)

一个面向终端的 AI 工作流工具，覆盖：

1. AI 使用技巧沉淀（`tip`）
2. 高价值对话一键沉淀并生成笔记（`capture`）
3. OpenAI / Gemini 模型统一切换（`ask` + `profile`）
4. 慢任务监控（`task`）
5. 论文入口（`paper`）

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
aiwf init
```

初始化后会生成：

- `~/.aiwf/config.json`: 模型路由配置
- `~/.aiwf/aiwf.db`: 本地 SQLite 数据
- `~/.aiwf/logs`: 任务日志
- `~/.aiwf/notes`: 沉淀笔记

## 模型配置

默认 profile：

- `fast` -> `openai/gpt-4.1-mini`
- `deep` -> `gemini/gemini-2.5-pro`
- `balanced` -> `openai/gpt-4.1`

设置 API Key：

```bash
export OPENAI_API_KEY="..."
export GEMINI_API_KEY="..."
```

## 常用命令

```bash
# 1) 沉淀 AI 技巧
aiwf tip add --title "Prompt 模板" --content "..." --tags prompt,template
aiwf tip list --tag prompt

# 2) 一键沉淀（从剪贴板抓取 + 自动生成笔记）
aiwf capture quick --tags codex,insight

# 也可以手动添加
aiwf capture add --title "有价值对话" --content "..." --tags codex --auto-note --profile deep

# 3) 多模型切换问答
aiwf ask "如何设计可扩展 agent 架构？" --profile deep
aiwf ask "给我 3 条快速建议" --profile fast

# 修改 profile 映射
aiwf profile set fast --provider openai --model gpt-4.1-mini
aiwf profile set deep --provider gemini --model gemini-2.5-pro

# 4) 慢任务监控（例如 Codex 任务）
aiwf task start --name "codex-长任务" --cmd "sleep 60 && echo done"
aiwf task list
aiwf task logs 1 --lines 80

# 5) 论文入口（先支持 arXiv 元数据 + 摘要总结）
aiwf paper arxiv --id 1706.03762
aiwf paper summarize 1 --profile deep
aiwf paper list
```

## 一键沉淀“按钮”思路

终端里可把 `aiwf capture quick` 绑定为快捷键或 alias：

```bash
alias cap='aiwf capture quick --tags codex'
```

然后复制你和 Codex/Gemini 的有价值内容，执行 `cap` 即可沉淀。

## 下一步扩展建议

- 接入你常用终端（iTerm2 / tmux）快捷键触发沉淀
- `paper` 增加 PDF 全文解析（如 `pdftotext` 或外部服务）
- 对 `task` 增加通知（系统通知 / webhook）

