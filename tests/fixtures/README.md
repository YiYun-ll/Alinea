# Alinea 可复现测试夹具

本目录包含 30 份无敏感信息、由程序构造的 DOCX/损坏包样本，以及生成器已知输入对应的 golden manifest。所有规范都是**假想测试规范**，不来自真实学校、出版机构、雇主或用户文档；没有声称经过人工 Microsoft Word 核验。

## 重新生成与校验

在仓库根目录 `D:\桌面\Alinea` 执行：

```bash
.venv/Scripts/python.exe tests/fixtures/generate_fixtures.py
```

只校验已有产物、不重新写入：

```bash
.venv/Scripts/python.exe tests/fixtures/generate_fixtures.py --validate-only
```

生成器使用 `python-docx`、`lxml`、`reportlab` 和 `Pillow`。它会同时重建 `examples/` 中的演示 DOCX、文本规范和 golden。内置校验包括：30 份数量与严格分类、JSON 可解析、属性/selector 契约值、文件大小与 SHA-256、文本锚点与 run 下标、有效 DOCX 重开、预期损坏样本重开失败、ZIP 安全边界、演示文件 10 个目标、9 个显式分页符、正文序列与媒体哈希一致、PNG 重开和 PDF 基本结构。

当前预期重开结果为：27 份 `REOPEN_OK`，2 份按预期失败（损坏 ZIP、非法 XML），1 份必须在重开/解压前安全拒绝（ZIP 边界元数据）。

## 严格分类

| category | 数量 | 样本 ID | 主要覆盖 |
|---|---:|---|---|
| `normal` 正常 | 5 | N01–N05 | 中文、英文、docDefaults、多级 basedOn、简单表格/图片/超链接、多节页眉页脚 |
| `single_property_error` 单属性错误 | 8 | S01–S08 | 字号、EastAsia 字体、粗体、对齐、行距、首行缩进、段前、节上边距；每份恰好一个 VIOLATION |
| `multi_property_error` 多属性错误 | 5 | M01–M05 | 同段不同 run、直接覆盖、行距/缩进/段前后、四边距、图题与表格批量目标 |
| `structural_edge` 结构边缘 | 6 | E01–E06 | 中英混排与未知主题字体、重复短句、长跨页、复合媒体、三节、未知 OPC part |
| `high_risk` 高风险 | 6 | H01–H06 | track changes、复杂域、OMML 公式、外部图片关系、损坏 ZIP、非法 XML、压缩比与路径穿越边界 |

高风险样本不包含真实恶意负载。H03 使用保留无效域名 `example.invalid`，不得联网获取；H04 只是截断字节；H05 只是未闭合 XML；H06 只有一个小型高压缩文本和名为 `../alinea-safe-boundary-marker.txt` 的边界条目，**不得解压该样本**。

## 目录结构

```text
tests/fixtures/
├── generate_fixtures.py
├── README.md
├── assets/
│   └── alinea-grid.png
├── data/
│   ├── normal/                  # 5 DOCX
│   ├── single_property_error/   # 8 DOCX
│   ├── multi_property_error/    # 5 DOCX
│   ├── structural_edge/         # 6 DOCX
│   └── high_risk/               # 6 个高风险文件，扩展名均为 .docx
└── golden/
    └── manifest.json
```

manifest 的 `file` 均相对于 `tests/fixtures/`。每份样本记录：

- `category`、`sample_id`、`file_size_bytes`、`file_sha256` 和已知结构事实；
- `paragraph_anchors`：唯一性、语义 selector 与文本锚点；
- `expected_supported_properties` 和 `expectations`：`actual`、`expected`、`run_index`、`fixable`、`locatable`、`expected_skip_reason`、允许的 XML 修改范围；
- `status`：`COMPLIANT`、`VIOLATION`、`UNVERIFIABLE` 或 `SKIPPED`；只有 `VIOLATION` 计入 `expected_issue_count`；
- `expected_errors` / `expected_degradations`：预期错误码、阶段与降级动作；样本级 `expected_skip_reasons` 为汇总集合；
- `rendering`：统一保留 `page_count: null` 和空 `locations`，等待实际渲染评测。

损坏包的顶层预期 API 错误码沿用需求文档的 `INVALID_DOCX`，`reason_code` 进一步区分 `CORRUPT_ZIP`、`INVALID_XML`、`UNSAFE_ZIP_PATH` 和 `COMPRESSION_RATIO_EXCEEDED`。H06 要求覆盖两个安全原因，顺序不限；这不是对尚未实现的具体 API 行为的实测声明。

## 确定性与边界

- 文本、样式值、关系 ID 顺序、图片像素和 golden 均由固定输入生成；manifest 保存当前环境下的文件大小与哈希。
- DOCX/ZIP 条目按名称排序，时间戳固定为 `2024-01-01 00:00:00`；核心属性时间也固定。因此相同依赖版本下重复运行应得到相同二进制哈希，而不是仅文本相同。
- 依赖版本变化可能改变 ZIP 或 PDF 的底层字节；语义 golden 不应因此静默改变，应审查哈希差异。
- golden 的 `actual` / `expected` 是生成器输入单位值。节长度在 OOXML 中量化为 twips，例如 20 mm 写成 1134 twips、精确回读为 20.0025 mm；应核对原始 XML，或为长度回读保留 0.01 mm 量化容差。
- `locatable` 只表示文本锚点是否具备定位资格，不是页面定位结果。重复短句应降级为 `LOCATION_AMBIGUOUS`；长段落可能产生多个片段。
- 没有生成或声称任何 DOCX 的实际渲染页数、页码或定位矩形。这些必须使用固定渲染器和字体环境另测。
- 主题字体是否存在、实际缺字回退和跨引擎分页同样不能由生成器预先宣称。
