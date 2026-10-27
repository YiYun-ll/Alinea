# Alinea 第二轮改进与验收报告

日期：2026-10-25

## 结论

本轮后端生命周期、渲染缓存、界面精修和动效可访问性改造已完成，并通过本地真实 DOCX、API、组件和 Chromium 浏览器验收。界面具有更明确的商业产品层次、操作反馈和响应式布局，同时保留原稿不可变、人工批准、包级 OOXML 补丁及 G1–G5 安全边界。

**这是本地迭代验收，不是生产发布或任意 Word 文档均可安全修复的保证。** 旧基线 `reports/acceptance.md` 保持不变。

## 本轮交付

### 后端

- 新增项目级授权的 `POST /jobs/{id}/retry` 和 `/cancel`。只有明确标记为可重试的失败可以重试，只有尚未被 Worker 原子领取的排队任务可以取消。
- 重试使用确定性的 `retry:{original_job_id}` 幂等键；重复请求同一失败任务返回同一个新任务。修复重试从持久请求中定位批准计划，重新检查项目归属、版本、规则与 digest，不会因新 Job ID 丢失计划绑定。
- API 启动时恢复本地未完成任务。RQ 模式不盲目重复执行运行中的任务，而是记录 `WORKER_RESTARTED` 可重试失败，等待人工检查结果。RQ Worker 使用显式 Redis 连接。
- API lifespan 每 15 分钟检查到期项目，复用项目删除路径清理原稿、修订版、预览、报告和数据库记录。
- LibreOffice 版本和字体环境哈希在进程内缓存，并按文件路径及元数据失效；PDF 缓存继续绑定 DOCX SHA 和完整渲染配置。未改变 preview SHA、revision 或定位坐标绑定。
- 真实端到端脚本新增“临时故障 → 安全重试 → 修复与复检”场景，而非只验证路由返回码。

### 前端与可访问性

- 首页采用文献编辑台式布局，增加错层证据卡、四步工作流、分步进入、卡片和按钮的细腻反馈。
- 增加路由/列表/Toast 过渡、原生 `<progress>`、统一 motion tokens 和可关闭的操作通知。
- 原生对话框具有进入、退出和 backdrop 过渡；ESC、取消与关闭按钮共用关闭路径，等待动画或有界超时后再关闭。
- 对话框退出能力通过真实离散 `display` 过渡探测；不支持时使用 `data-closing` 和 `getAnimations()` 安全回退，不让 DOM 提前消失。
- 支持系统 `prefers-reduced-motion` 和手动“动效/静态”选择。未手动选择时监听系统变化；手动选择持久保存在当前浏览器。系统的减少动效设置保持为安全下限。
- 减少动效按组件关闭或减慢，不再使用全局 `0.01ms` 压制；平滑滚动、加载旋转和不确定进度均有相应处理。
- 小屏导航独立换行；390px 真实项目历史页加入自动化边界检查。表格和项目导航保留内部滚动，不把长标识强行缩小。

## 实际验证

| 检查 | 实际结果 | 口径 |
|---|---|---|
| 后端全量测试 | **214 passed，1 skipped** | `python -m pytest -q`；55.08 秒 |
| 额外真实 LibreOffice 冒烟 | **1 passed** | 显式 `ALINEA_RUN_LO_SMOKE=1`；真实 PDF 与中文定位，79.94 秒 |
| Ruff | **通过** | `ruff check .`，无错误 |
| Python 依赖一致性 | **通过** | `pip check`，无损坏依赖 |
| 前端组件测试 | **15 passed / 7 files** | Toast、进度、动效偏好、对话框、历史任务操作等 |
| 前端 lint / 类型 / 构建 | **通过** | ESLint 无警告；生产 build 含 `vue-tsc --noEmit` |
| Playwright | **2 passed / 29.5 秒** | 完整业务流程 23.9 秒；移动端与动效流程 3.2 秒；控制台无错误 |
| 真实故障重试 | **通过** | 一次注入临时修复失败后重试成功；2 个 repair Job、1 个发布版本 |
| 文档保真 | **通过** | 选修 2/2 项解决；文本与媒体保持一致；G0 WARN、G1–G5 PASS |
| 下载 | **通过** | 实际保存修订 DOCX、JSON 报告与 Markdown 报告并检查文件 |
| 权限与删除 | **通过** | 其他项目令牌不能重试；删除后旧下载 URL 失效 |
| 桌面与窄屏 | **通过** | 内置浏览器实际页面检查；Playwright 390px 首页、新建页、真实项目历史页无根级横向溢出 |

后端最终完整脚本耗时 **11.016 秒**：20 个初始明确违规、19 个可修复项、42 个可信定位；选择性修复后剩 18 个未选违规、40 个可信定位。该时间使用当前机器与已有渲染缓存，不能替代空缓存转换性能。

## 缓存性能实测

测量脚本：`scripts/benchmark_iteration2.py`。样本：`examples/alinea-demo.docx`，10 页，SHA-256 为 `0a77ffc978543c0be08146fc227fe373ae4bb5b4f3423bd3e36ba7e0b474a0ef`。脚本清空自己的测量目录，使用两个独立空 PDF 缓存，不剔除较慢结果。

环境：Windows 11；11th Gen Intel Core i7-11800H @ 2.30GHz；Python 3.12.2；Node.js 22.11.0；npm 10.9.0；LibreOffice 26.8.1.1；渲染 profile `local-lo`；字体环境 SHA-256 `013a760fe5c155b669bc88daa3cbbb8db609378a0fca707480aa8cc02abc9ca8`。

| 项目 | 实测秒数 |
|---|---:|
| 本进程首次 profile / 版本与字体环境探测 | 4.192045 |
| 同一 renderer 再次读取 profile | 0.000002 |
| 新 renderer 使用进程内环境缓存 | 0.246833 |
| 独立空 PDF 缓存，第一次 | 56.590029 |
| 独立空 PDF 缓存，第二次 | 62.503474 |
| 第一次缓存命中（新 renderer） | 0.136417 |
| 第二次缓存命中 | 0.080360 |

试跑的空缓存转换还曾记录 66.630269 秒。额外真实 1 页冒烟转换记录 79.517 秒；这些数字说明本机转换延迟存在明显环境差异，不能推断为固定冷启动时间。缓存命中与对应原 PDF 的 SHA-256 一致；独立再次导出的 PDF 哈希不要求相同。未宣称提升百分比、P95、生产并发能力或跨机器一致性。

## 安全与代码复核

- 项目 token 只以 SHA-256 持久化；新重试/取消路由复用项目授权与资源归属检查。
- 没有通过重试绕过人工批准、旧值检查或原稿不可变约束；没有强行终止正在执行的任务。
- `apps`、`packages`、`scripts`、`tests` 和 `docs` 中未检出真实模型密钥。密钥仅作为本地进程环境输入，没有写入源码、`.env.example` 或报告。
- HTTP 接口未回显完整 headers、环境变量或 CloudBase runtime context。已执行相关 CloudBase code-review 规则复核；本项目未使用 CloudBase SDK，也未创建或部署 CloudBase 资源，云平台特定 Auth/数据库/Storage 规则不构成已部署能力。
- mypy 的重复 `conftest` 收集问题已通过项目命名空间配置修正。标准 `python -m mypy .` 当前仍报告 **47 errors / 14 files / 97 source files**，主要是动态 JSON、第三方库和类型边界；**不能声称全量 Python 类型检查通过**。

## 产物与复现

- 测试与启动说明：`README.md`。
- 接口、任务恢复、缓存和保留策略：`docs/API.md`、`docs/ARCHITECTURE.md`、`docs/SECURITY.md`。
- 完整后端保真/重试验证：`scripts/smoke_e2e.py`、`.data/e2e/result.json`。
- 性能原始结果：`.data/iteration2-benchmark/results.json`。
- 浏览器用例：`apps/web/tests/e2e/full-flow.spec.ts`。
- 最新完整流程录像：`reports/artifacts/iteration2-full-flow.webm`。
- 最新移动端录像：`reports/artifacts/iteration2-mobile.webm`。
- 本地页面：`http://127.0.0.1:5173`；API 健康检查：`http://127.0.0.1:8000/health`。

## 尚未完成与限制

1. **类型治理**：47 项 mypy 错误仍待处理，不能以 Ruff、pytest 或 Vue 类型检查替代。
2. **部署**：未进行 Docker/Compose 构建、镜像 digest 固定、公网或 CloudBase 部署，也未验证真实 Redis/RQ Worker 集群。
3. **Word 视觉核验**：未在 Microsoft Word 中人工核验分页与字体；Word 和 LibreOffice 可能有不同排版结果。
4. **性能覆盖**：没有 30 页 P95、生产并发、跨浏览器全矩阵或多机器数据。当前浏览器实测为 Chromium。
5. **模型抽取**：本轮未改变模型边界，也未重新执行长 PDF 大模型抽取基准；沿用旧报告的实测记录，不将其当作本轮新增结果。
6. **复杂文档**：复杂 OOXML、扫描件、复杂阅读顺序和不受支持对象仍须按支持矩阵降级或人工处理。
7. **许可证**：未重新生成 SBOM 或进行法律审查；本轮未新增运行时依赖，但生产发布仍需复核传递依赖、字体和镜像许可。
