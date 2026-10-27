# Alinea

**Alinea — Document Formatting, Made Verifiable.** 让每一处排版都有依据。

Alinea 是一个本地可自托管的 DOCX 格式检查与精准修复 Web MVP。它把用户确认的规范变成原子规则，用确定性程序检查 WordprocessingML，在 LibreOffice 生成的 PDF 上标出可信位置，并只在人工批准后修改原文件副本。

## 安全边界

- 原始 DOCX 不可变；不会用 HTML、全文替换或模型生成的文档重建原稿。
- AI 只抽取规范，不获得 Shell、文件系统或修复工具；无 AI 时可使用预设与手动规则。
- 每次修复绑定文档 SHA、规则 digest、检查结果和旧格式值，并经过 G0–G5。
- 定位置信度不足时保留段落和文本证据，不画猜测高亮。
- 默认不上传 DOCX 正文给模型；规范片段会发往所配置的第三方模型，请只使用非敏感/脱敏材料。

## 本地运行

### 要求

- Python 3.12、Node.js 22、npm。
- LibreOffice Writer（预览与页面定位必需；纯结构检查可降级运行）。
- Windows 可用 `py -3.12`；macOS/Linux 使用 `python3.12`。

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -e '.[dev]'
npm ci --prefix apps/web
cp .env.example .env
```

在 `.env` 中设置 `ALINEA_LLM_API_KEY` 才会启用模型解析。不要将 `.env` 提交到版本库。渲染器可通过 `ALINEA_SOFFICE_PATH` 指定，也会探测工作区 `.tools/LibreOffice` 和系统安装。

启动 API（工作目录为仓库根目录）：

```bash
.venv/Scripts/python -m uvicorn app.main:app --app-dir apps/api --reload
```

另一个终端启动 Web：

```bash
npm run dev --prefix apps/web
```

打开 `http://127.0.0.1:5173`。可上传自己的 DOCX，或使用真实生成的演示文档。演示规范是假想规范，不是任何学校的官方标准。

### 完整操作路径

1. 上传 DOCX 并选择规范。默认提供真实可用的 `general_report`、`thesis_demo` 非官方演示预设，选择文件后自动命名；自定义文本、PDF 和预设 ID 可按需展开。
2. 在检查确认区核对文档、规范和启用规则。批准规范后开始检查；需要逐条编辑时仍可进入完整规则页。随后查看证据并选择要修复的问题。
3. 阅读易读的 before→after 差异，独立批准修复计划，再单独执行。完整 digest、目标节点和 OOXML 约束可展开核查。
4. 在“结论 / 对照 / 下载”中切换结果视图，检查 G1–G5、比较原版与修订版，下载 DOCX、PDF、JSON/Markdown 报告。

### 任务恢复与界面偏好

- 项目内使用“确认规范 → 检查与选择 → 批准与修复 → 报告与下载”四步导航。当前步骤与真实完成状态来自服务端，未完成的结果步骤不可进入。
- 检查优先复用相同文档、规则和检查器版本的成功结果或活动任务，不重写历史 Inspection。刷新结果只读取服务端数据，不发起新检查或重复渲染。
- “任务与版本”页显示真实进度。服务端标记为可重试的失败任务可安全重试；只有尚未开始执行的排队任务可取消。重试沿用原始请求和批准约束，重复提交同一失败任务的重试会返回同一新任务，且不会清空成功历史。
- 本地执行模式在 API 重启后恢复未完成任务。RQ 模式不会自动重复执行可能仍在 Worker 中运行的任务；对应任务会失败并标记为需要人工检查后重试。
- 到期项目及其原稿、修订版、预览和报告由后台维护任务每 15 分钟清理，也可在项目中主动删除。
- 页面支持步骤/面板/折叠/对话框过渡、操作通知和原生进度条，并自动跟随系统“减少动态效果”设置；开启系统减少动效后，页面过渡、平滑滚动和持续动画会关闭或减慢。
- 缓存以文档 SHA 和完整渲染配置为键，避免重复 PDF 转换；字体与渲染器环境缓存按文件元数据失效。缓存耗时和冷转换数据见 `reports/iteration-2.md`。

## 测试与验收

```bash
.venv/Scripts/python -m pytest
.venv/Scripts/python -m ruff check .
npm run typecheck --prefix apps/web
npm run lint --prefix apps/web
npm run test --prefix apps/web
npm run build --prefix apps/web
npm run test:e2e --prefix apps/web
```

重新生成 30 份合成/脱敏夹具与演示文件：

```bash
.venv/Scripts/python tests/fixtures/generate_fixtures.py
```

生成当前实际安装的依赖许可证清单：

```bash
.venv/Scripts/python scripts/generate_sbom.py
```

额外真实 LibreOffice 冒烟（需要本机渲染器）与第二轮缓存测量：

```bash
ALINEA_RUN_LO_SMOKE=1 .venv/Scripts/python -m pytest -q tests/unit/alinea_mapping/test_real_renderer_smoke.py
.venv/Scripts/python scripts/benchmark_iteration2.py
```

实测指标、机器/渲染环境和未验证项见 `reports/benchmark.md`、`reports/iteration-2.md` 与 `reports/iteration-3.md`。目标值不得当作实测结果。`.venv/Scripts/python -m mypy .` 可检查当前 Python 类型债务，但目前仍有未解决的类型错误，不能列为通过的验收项。

## Docker Compose（可选）

```bash
docker compose up --build
```

Compose 包含 Web、API、RQ worker、PostgreSQL 与 Redis，Web 默认在 `http://localhost:8080`。首次构建会安装较大的 LibreOffice/Noto CJK 依赖。生产部署前必须实际构建、固定镜像 digest、审查许可证和限制渲染网络；本地没有 Docker 时不能以该配置替代实测。

## 支持范围

| 能力 | MVP |
|---|---|
| 中/西字体、字号、粗体 | 检测；受支持普通对象可审批修复 |
| 对齐、倍数/固定行距、缩进、段前后 | 检测；受支持普通对象可审批修复 |
| 页边距、页面尺寸 | 检测；明确分节作用域后审批 |
| 样式继承 | docDefaults、段落/字符 basedOn 链与直接格式的受支持子集 |
| 简单表格/超链接/图片 | 结构保留与保真 Gate；复杂布局定位可降级 |
| 重复/跨页文本 | 上下文消歧与多页片段；不可靠则不高亮 |
| Track Changes、OLE、宏、加密文件 | 拒绝或只读诊断，不自动修复 |
| 公式、复杂域、文本框、复杂合并表格 | 人工复核，不自动修复 |
| 扫描 PDF OCR、在线全文编辑、协作、账号/计费 | 不属于本版本 |

LibreOffice 与 Microsoft Word 的字体替换、布局和分页可能不同。静态规则符合与特定渲染环境的视觉结果分别报告。

## 文档

- `docs/ARCHITECTURE.md`：模块与版本一致性
- `docs/API.md`：REST/SSE 契约
- `docs/RULE_DSL.md`：原子规则与单位
- `docs/SECURITY.md`：威胁与数据保护
- `docs/SUPPORTED_FEATURES.md`：支持矩阵
- `docs/BENCHMARK.md`：评测口径
- `reports/SBOM.json`：实际依赖与许可证清单
- `specs/alinea-mvp/`：EARS 需求、设计与任务追踪
