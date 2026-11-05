# 参与贡献

感谢关注 Alinea！欢迎提交问题报告、功能建议、文档改进和代码贡献。参与本项目时，请遵守[行为准则](CODE_OF_CONDUCT.md)。

## 开始之前

- 搜索已有 Issues 和 Pull Requests，避免重复工作。
- 报告问题时附上可复现步骤、实际结果、预期结果和运行环境；请使用脱敏文档，不要上传论文原稿、密钥或其他敏感数据。
- 对较大的功能或架构调整，先创建 Issue 讨论方案，再开始实现。
- 安全漏洞请按照 [SECURITY.md](SECURITY.md) 私密报告，不要创建公开 Issue。

## 本地开发

```bash
git clone https://github.com/YiYun-ll/Alinea.git
cd Alinea
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
npm ci --prefix apps/web
cp .env.example .env
```

Windows 的虚拟环境路径为 `.venv/Scripts/python`，环境文件可用 `Copy-Item .env.example .env` 创建。完整环境要求与启动方式见 [README.md](README.md#快速开始)。

## 提交 Pull Request

1. Fork 仓库，并从 `main` 创建主题分支。
2. 保持变更聚焦，代码风格与所在模块一致；用户可见行为变化应同步更新文档和测试。
3. 不提交 `.env`、模型密钥、真实用户文档、生成的缓存或测试输出。
4. 运行与变更相关的检查。完整检查命令如下：

   ```bash
   .venv/bin/python -m pytest
   .venv/bin/python -m ruff check .
   npm run typecheck --prefix apps/web
   npm run lint --prefix apps/web
   npm run test --prefix apps/web
   npm run build --prefix apps/web
   PYTHON=.venv/bin/python npm run test:e2e --prefix apps/web
   ```

   Windows Git Bash 使用 `.venv/Scripts/python`；首次运行 Playwright 前需执行 `npx --prefix apps/web playwright install chromium`。
5. PR 中说明修改目的、验证方式和已知限制。涉及界面时附截图；涉及文档修复时说明完整性门禁和真实流程验证结果。

如果某项检查无法运行，请在 PR 中明确说明，不要将未验证的变更标记为已验证。维护者可能会要求拆分 PR 或补充测试。

## 许可证

提交贡献即表示你同意按 [Apache License 2.0](LICENSE) 授权该贡献。请确保你有权提交所附代码、文档和测试数据；第三方材料必须保留原有版权与许可证声明。
