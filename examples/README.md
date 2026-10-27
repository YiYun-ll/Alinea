# Alinea E2E 假想演示数据

`guideline.txt` 与 `guideline.pdf` 描述的是一套**完全假想的格式规范**，仅用于 Alinea 软件测试，不代表任何真实机构要求。所有预期来自 `tests/fixtures/generate_fixtures.py` 的已知输入，未经人工 Microsoft Word 核验。

## 文件

| 文件 | 用途 |
|---|---|
| `alinea-demo.docx` | 含 10 个可控格式偏差的完整 E2E 输入，含真实中文/英文正文、标题、图片、简单表格和超链接 |
| `alinea-demo-compliant.docx` | 相同文本与媒体的对照版，10 个目标均为合规值 |
| `alinea-demo.golden.json` | 精确列出 D01–D10 的 selector、property、唯一段落文本锚点、适用的 run_index、actual/expected、修复与定位资格 |
| `guideline.txt` | 与 PDF 内容一致的纯文本假想规范 |
| `guideline.pdf` | ReportLab 生成的可抽取文本 PDF，使用英文和内置 Helvetica，避免嵌入 CJK 字体 |

从仓库根目录重建全部演示数据及 30 份测试夹具：

```bash
.venv/Scripts/python.exe tests/fixtures/generate_fixtures.py
```

## 10 个受控目标

| ID | selector / property | 错误版 actual | 规范 expected |
|---|---|---:|---:|
| D01 | body / `font.eastAsia` | SimHei | SimSun |
| D02 | heading_1 / `font.size_pt` | 18 pt | 16 pt |
| D03 | body / `font.size_pt` | 10.5 pt | 12 pt |
| D04 | body / `font.bold` | true | false |
| D05 | body / `paragraph.alignment` | center | both |
| D06 | body / `paragraph.line_spacing` | 1.0 | 1.5 |
| D07 | body / `paragraph.first_line_indent_chars` | 0 | 2 |
| D08 | body / `paragraph.space_before_pt` | 12 pt | 0 pt |
| D09 | body / `paragraph.space_after_pt` | 12 pt | 0 pt |
| D10 | section / `section.margin_top_mm` | 20 mm | 25.4 mm |

D10 是全文唯一节的一个节属性目标，不是十个页面各一个边距问题。每个目标的精确锚点以 golden JSON 为准。golden 中 20 mm 是生成器输入值；OOXML 实际存为 1134 twips，精确回读为 20.0025 mm，这是单位量化而非第 11 个目标。

## 分页与 E2E 使用边界

两个演示 DOCX 都实际包含 **9 个显式分页符**，形成 **10 个逻辑页块**，每块内容保持简短。这里的“10 页”指显式分页结构；没有运行 Word/LibreOffice 渲染，因而不把实际 PDF 页数、页面索引或定位矩形写成真值。完整 E2E 应在固定渲染器与字体环境中另行确认实际页数。

建议流程：上传 `alinea-demo.docx` 和 `guideline.pdf`（或文本版），抽取并审批规则，对照 D01–D10 检查 Issue；只批准部分目标后验证选择性修复、正文序列不变、媒体哈希不变与重开；用 `alinea-demo-compliant.docx` 验证这 10 个目标均不再违规。页面跳转与高亮必须以实际渲染结果验收，不能仅由本目录 golden 推断。
