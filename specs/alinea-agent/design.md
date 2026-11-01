# Alinea 完整智能体改造设计

## 架构

新增 `AgentRun → bounded model/tool loop → domain tool facade → existing services` 编排层。`Job` 继续表示后台执行任务，`AgentRun` 表示一次可恢复的决策会话，两者关联但不混用状态。

```text
Vue AgentPanel → Agent API → AgentRun/AgentEvent
                                  ↓
                       OpenAI Agents SDK + bounded tools
                                  ↓
       rules / document structure / inspection / repair-plan services
                                  ↓
                deterministic engines and existing approval gates
```

继续使用项目已有 `openai-agents`、Pydantic、SQLAlchemy、FastAPI、Vue、Pinia 和 Lucide，不增加编排框架。

## 数据与接口

- `AgentRun`：项目、目标、状态、当前规则/检查/修订关联、步数、Token、输入摘要、结构化问题、结果和错误。
- `AgentEvent`：递增序号、事件类型、工具名、状态、耗时和脱敏负载。
- API：创建运行、获取运行与事件、提交澄清答复、重试失败运行；文档修复审批与执行沿用现有 API。
- 工具输出只含 ID、摘要、候选数据和必要证据；日志不保存密钥或完整文档正文。

## 工具边界

第一批工具覆盖规范读取、候选验证、结构摘要、角色建议、检查和检查摘要、修复计划预览、报告读取。所有 ID 都在服务端重新校验项目归属。检查要求已批准规则，修复计划只接受明确违规且安全的目标。批准与执行不是模型工具。

## 状态与恢复

运行状态包括 `QUEUED/RUNNING/NEEDS_CLARIFICATION/SUCCEEDED/FAILED`。每次工具调用追加不可变事件；用户答复创建新的输入事件并继续同一运行。限制模型步数、工具步数、字符和 Token，超过限制显式失败。服务重启后，本地未完成运行可重新入队，已通过执行键避免重复副作用。

## 前端

沿用石板蓝品牌与现有字体。桌面采用主内容加右侧 Agent 栏的不对称工作区，窄屏使用可关闭抽屉。默认显示结论、必要澄清和主操作；工具细节放入折叠时间线。减少标签、重复标题和说明性卡片，保持现有四步导航与审批界面。

## 验证

单元测试覆盖工具契约、权限、状态机、预算、来源证据和角色隔离；集成测试覆盖真实检查及计划调用；模型测试使用临时环境凭据；浏览器覆盖规则澄清、自然语言检查、计划准备、原审批执行、刷新恢复和窄屏布局。
