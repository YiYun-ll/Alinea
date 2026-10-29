# 第五轮：石板蓝主题与后端正确性修复

日期：2026-10-29

上一轮界面与流程优化已先提交为 `62785be`，并推送到 `origin/main`。本轮新增修改保留在工作区。

## 配色

主操作色改为偏灰的石板蓝 `#4b6588`，搭配墨蓝正文 `#29394e`、浅灰纸面 `#f7f8fa` 和低饱和蓝灰边界。同步调整按钮、导航、筛选、表单、预览、证据和首页示意；成功、警告、失败继续保留语义色。

## 后端修复

1. **存储模块未进入版本控制范围**：原 `.gitignore` 中的 `storage/` 同时排除了 `apps/api/app/storage` 源码。改为仅忽略仓库根目录 `/storage/`，使 `__init__.py`、`local.py` 可正常纳入源码交付。独立源码导出目录的 API、LocalStorage 导入验证通过。
2. **连续修复重试失败**：第一次重试的 Job key 已变成 `retry:{job_id}`，后续失败与重试仍按原执行 key 查询计划，导致状态不更新或找不到计划。改为读取持久请求中的计划 ID，并校验项目归属和计划摘要。
3. **失败诊断报告丢失**：完整性检查阻断后，候选记录与报告元数据会随异常回滚。现在先持久化阻断诊断，再由 Worker 记录失败；活跃版本不变，候选 DOCX 仍禁止下载，JSON/Markdown 报告可查看。
4. **无法验证被误算为已解决**：选中目标在复检中变为 UNKNOWN 或 POSSIBLE_VIOLATION 时，原先只检查明确违规集合，因此可能报告 PASS。现在这些目标计入未解决，报告为 INDETERMINATE，G5 记录 `selected_unverifiable`。
5. **重复渲染触发不可变存储冲突**：同一 revision/profile 的 PDF 总写入 `preview.pdf`，再次检查可能抛出 FileExistsError。现在文件名包含实际 PDF SHA-256；相同字节验证后复用，不同输出写入不同对象，原文件不覆盖。
6. **已有 PDF 被后续结构检查遮挡**：预览查询原先直接取最新 Inspection，即便该记录没有 PDF。现在仅查询成功且登记了 PDF 的检查。
7. **检查与预览可能错配**：预览接口新增可选 SHA-256 参数，返回该检查对应的精确 PDF，未知指纹返回 404。前端预览缓存同时绑定 revision 与 PDF SHA，旧异步响应不能替换新预览；没有预览的检查会清理旧 PDF。
8. **显式配置未用于服务层**：`create_app(settings)` 原先只配置数据库、CORS 和执行器，存储等服务仍读默认配置。现在在应用生命周期内统一运行配置；关闭时等待执行中的本地任务并取消尚未启动的执行器任务，再恢复先前配置。排队数据库记录留给下次启动恢复。

兼容已有预览元数据与文件路径；新增 PDF 指纹参数可选，未改变项目鉴权、原稿不可变或审批边界。当前进程仍使用一个共享数据库及运行配置，未扩展为同进程多应用隔离架构。

## 验证

- 新增 7 项后端回归，在修复前分别复现失败，修复后全部通过。
- 后端全量：**240 passed，1 skipped，42.02 秒**。跳过项是默认关闭的额外 LibreOffice 冒烟；完整业务脚本与浏览器流程使用真实文档及渲染器。
- 前端：**40 项测试通过，13 个文件**；包括同 revision 不同 PDF 指纹的异步竞态回归。
- Playwright：**7 passed，2.8 分钟**；涵盖真实桌面检查、审批修复、计划刷新恢复、下载、默认规范上传、390px 流程及前一轮故障回归。
- Python Ruff、前端 TypeScript/ESLint、生产构建、`pip check` 均通过。
- 源码导出导入验证通过；存储源码不再被 Git 忽略。
- 视觉复核：真实演示从新建到修复报告，未捕获页面运行错误；上传页在 320、390、768、1440px 下均无页面横向溢出。

浏览器耗时包含首次冷渲染，不能与前轮缓存命中的耗时直接比较。本轮未进行 Docker、公网、真实 RQ 集群或多进程竞争验收；原有 Python 类型债务不在此次修复范围。

## 证据

- 后端回归：`tests/integration/alinea_api/test_backend_regressions.py`
- 前端指纹竞态：`apps/web/src/stores/workspace-regressions.spec.ts`
- API 契约与生命周期说明：`docs/API.md`、`docs/ARCHITECTURE.md`
- 页面截图：`reports/artifacts/iteration5-home.png`、`iteration5-setup.png`、`iteration5-inspection.png`、`iteration5-repair.png`、`iteration5-results.png`、`iteration5-upload-1440.png`、`iteration5-upload-390.png`
