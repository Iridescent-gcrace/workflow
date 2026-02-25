# AIWF (All-in-One Workflow Terminal)

一个面向终端的 AI 工作流工具，覆盖：

1. AI 使用技巧沉淀（`tip`）
2. 高价值对话一键沉淀并生成笔记（`capture`）
3. OpenAI / Gemini 模型统一切换（`ask` + `profile`）
4. 慢任务监控（`task`）
5. 论文入口（`paper`）
6. AI 轮询审查（`review`）
7. 手机远程入口（`remote`）

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
wf init
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

## 超短命令（推荐）

`wf` 是短入口（等价于 `aiwf`）。

```bash
# 一键沉淀（剪贴板）
wf x --tags codex

# 快速问答 / 深度问答
wf q "3条建议，简短"
wf q "帮我设计 agent 架构" --profile deep

# 任务
wf j s --name "codex-任务" --cmd "sleep 30 && echo done"   # start
wf j l                                                      # list
wf j g 1 --lines 100                                        # logs

# 仪表盘
wf d

# 审查
wf rv n --goal "判断任务是否完成，给下一步"
wf rv l --goal "直到完成再结束" --task-id 1 --interval 45 --max-rounds 12
```

## 全量命令示例

```bash
# 1) 沉淀 AI 技巧
wf tip add --title "Prompt 模板" --content "..." --tags prompt,template
wf tip list --tag prompt

# 2) 一键沉淀（从剪贴板抓取 + 自动生成笔记）
wf capture quick --tags codex,insight

# 也可以手动添加
wf capture add --title "有价值对话" --content "..." --tags codex --auto-note --profile deep

# 3) 多模型切换问答
wf ask "如何设计可扩展 agent 架构？" --profile deep
wf ask "给我 3 条快速建议" --profile fast

# 修改 profile 映射
wf profile set fast --provider openai --model gpt-4.1-mini
wf profile set deep --provider gemini --model gemini-2.5-pro

# 4) 慢任务监控（例如 Codex 任务）
wf task start --name "codex-长任务" --cmd "sleep 60 && echo done"
wf task list
wf task logs 1 --lines 80

# 5) 论文入口（先支持 arXiv 元数据 + 摘要总结）
wf paper arxiv --id 1706.03762
wf paper summarize 1 --profile deep
wf paper list

# 6) 任务/代码 AI 审查
wf review now --goal "当前任务是否可交付" --task-id 1
wf review loop --goal "直到可交付为止" --task-id 1 --interval 60 --max-rounds 10
```

## 一键安装“当前对话沉淀”脚本（iTerm/Warp）

执行一次安装：

```bash
bash scripts/install_onekey_capture.sh
source ~/.zshrc
```

安装后你会得到：

- `wfc`：一键沉淀当前终端对话
- `wfs`：同上，但静默（不弹通知）
- 可选全局热键：`Cmd+Shift+S`（由 `skhd` 提供）

直接用：

```bash
wfc
wfc --with-note
```

工作方式：

- iTerm: 直接读取当前 session 的最近输出并沉淀
- Warp: 自动触发 `Copy Outputs` 后沉淀（依赖 Warp 默认复制输出快捷键）

只想安装命令，不安装全局热键：

```bash
bash scripts/install_onekey_capture.sh --no-hotkey
```

## 手机远程下发任务

1. 生成并保存 token：

```bash
wf rm t --save
```

2. 启动远程服务：

```bash
wf rm s --host 0.0.0.0 --port 8787
```

3. 手机通过 HTTP 调用（建议放在 Tailscale/VPN 内网）：

```bash
TOKEN="你的token"

# 查看状态
curl -H "Authorization: Bearer $TOKEN" http://你的电脑IP:8787/status

# 提问
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"prompt":"给我今天的任务计划","profile":"fast"}' \
  http://你的电脑IP:8787/ask

# 启动后台任务
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"mobile-task","cmd":"echo hello && sleep 5 && echo done"}' \
  http://你的电脑IP:8787/tasks

# 查询任务列表
curl -H "Authorization: Bearer $TOKEN" http://你的电脑IP:8787/tasks
```

## 下一步扩展建议

- `paper` 增加 PDF 全文解析（如 `pdftotext`）
- `remote` 接入 Telegram / 企业微信 bot 做推送通知
- `review loop` 增加“自动触发下一条命令”策略
