# 第七轮：智能体对话体验与完整验收

日期：2026-11-01

## 界面与操作优化

- 对话区改为连续消息视图，支持终端任务追问和显式新建任务。
- 空状态只提供当前上下文可用的操作；长结论默认六行折叠，工具轨迹继续按需展开。
- 输入区固定在面板底部，不再受历史记录下拉是否存在影响。
- 1144px 等常见桌面宽度默认展示侧栏；960px 以下使用原生 `<dialog>`，支持自动聚焦、Esc 关闭、焦点返回及滚动阻断。
- Agent 创建的 RepairPlan 自动恢复到 Repair store、对应 Inspection 和 Revision，刷新后仍可继续批准。

## 端到端发现并修复的问题

1. 历史记录下拉缺省时，Grid 自动放置把输入区放入弹性行，导致其未落底；改为 Flex 列布局。
2. 后台任务轮询会强制切换当前任务；轮询只更新数据，不再改变用户主动选择。
3. 追问请求失败会丢失输入；错误向上传递后由输入区恢复原消息。
4. Agent 已在服务端创建计划，修复页却提示先选择问题；新增按计划 ID 加载及持久恢复。
5. 刷新读到已完成 AgentRun 时未同步关联资源；终端任务现在也执行恢复。
6. 绝对 `VITE_API_BASE_URL` 场景下，Artifact 下载重复拼接 `/api/v1` 导致 PDF 404；统一归一化同源 URL 并增加单测及 Playwright 下载回归。
7. 媒体查询监听改为具名处理并在卸载时移除，项目主区域移除嵌套 main landmark。

## 真实模型与业务闭环

使用 DeepSeek 从对话框请求“为所有明确且可安全修复的问题准备计划，不执行修复”。模型完成 3 次工具调用并生成 19 个操作、17 个影响节点的 DRAFT 计划。

随后在同一浏览器项目中验证：计划跳转、刷新恢复、人工批准、独立执行、候选版本复检。报告为 19/19 已解决、0 项未解决，G1–G5 全通过；输入安全警告仍独立保留。模型没有批准或执行权限。

## 验收结果

- 后端全量：247 passed，1 skipped。跳过项仍为默认关闭的额外 LibreOffice 冒烟。
- 前端：48 passed，16 个测试文件。
- Playwright：7 passed，约 1.8 分钟；包含真实检查、批准修复、结果恢复、移动流程、控制台错误检查和 PDF 下载。
- Ruff、Vue TypeScript、ESLint、生产构建全部通过。
- 真实浏览器手动复核：1144px 桌面侧栏、长结论折叠、390px 报告页、移动输入自动聚焦、Esc 关闭及焦点返回。
- 下载：修订 DOCX、原版 DOCX、PDF、JSON、Markdown 均通过真实浏览器流程验证；PDF 已纳入完整 Playwright 测试并实际保存。

## 证据

- `reports/artifacts/iteration7-agent-repair.png`
- `reports/artifacts/iteration7-agent-mobile.png`
- `reports/artifacts/iteration7-results.png`
- PDF 下载回归：`apps/web/tests/e2e/full-flow.spec.ts`
- URL 归一化单测：`apps/web/src/lib/api.spec.ts`

## 边界

本轮完成本地完整业务与浏览器验收，不代表 Docker、公网、真实 RQ 集群、多进程竞争或人工 Microsoft Word 视觉验收完成。角色建议仍不会自动覆盖程序角色；既有 mypy 类型债务不在本轮范围。
