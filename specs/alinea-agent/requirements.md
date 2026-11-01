# Alinea 完整智能体改造需求

## 目标与边界

将现有确定性 DOCX 检查修复 MVP 升级为可实际使用的单 Agent 系统。Agent 负责规范理解、工具选择、歧义澄清、文档角色建议、任务编排和结果解释；现有程序继续负责事实检查、文件修改和质量判定。不引入多智能体，不允许模型直接写文件、执行 Shell 或自行批准操作。

## 用户故事

1. 用户上传规范后，Agent 能读取相关片段、验证候选规则，并在信息不足时提出具体问题。
2. 用户能查看 Agent 当前结论和必要的工具轨迹，而不必理解模型或 OOXML 术语。
3. 用户能用自然语言请求检查、解释问题或准备安全修复，系统将其转换为受约束的领域操作。
4. 对角色不明的少量段落，Agent 能给出有依据、可确认的建议。
5. 模型不可用或任务中断时，用户仍能使用原有规则流程，并能恢复或重试 Agent 任务。

## EARS 验收标准

1. When a user starts an Agent task, the system shall persist an AgentRun with project scope, immutable input digest, status, budget and timestamps.
2. When the model selects a tool, the system shall validate its arguments, verify project ownership and record a redacted structured result before allowing another step.
3. When rule evidence is missing, rules conflict or scope is ambiguous, the system shall return NEEDS_CLARIFICATION or a draft with explicit uncertainties instead of inventing requirements.
4. When paragraph roles are requested, the system shall send only bounded excerpts and return source-separated RoleSuggestion records; model suggestions shall not silently replace parser or user roles.
5. When inspection is requested through the Agent, the system shall require the exact approved RuleSet and use the existing inspection service and evidence bindings.
6. When repair preparation is requested, the system shall select only existing SAFE_SINGLE_TARGET confirmed Issues and create a DRAFT RepairPlan through the existing service.
7. The system shall not expose repair execution or approval as model-callable tools; execution shall continue to require the existing authenticated user approval path.
8. When a run exceeds step, token or time limits, the system shall stop with an explicit resumable or failed state and preserve its event history.
9. When the model is unavailable, the system shall retain preset/manual rule, inspection and approved repair workflows.
10. When the user opens the workspace, the interface shall present the current Agent conclusion, clarification and primary action with responsive layout and accessible controls, while keeping detailed traces progressively disclosed.
11. When a prompt-injection, cross-project reference, stale revision, forged approval or invalid tool output is tested, the system shall reject the unsafe effect and retain an auditable result.
12. Before delivery, the system shall pass backend/frontend static checks and tests, a real model smoke test, and a real browser workflow without new runtime errors.

## 非目标

- 不让 Agent 自由编辑正文或生成整篇 DOCX。
- 不在本轮实现 OCR、旧版 DOC、复杂 OOXML 自动修复、多用户协作或生产公网部署。
- 不把模型解释当作 Issue、PASS 或质量 Gate 的事实来源。
