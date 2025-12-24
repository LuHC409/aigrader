WordBatchAssistant
==================

WordBatchAssistant 是一个用于批量处理 Word (`.docx`) 文件并通过 LLM 执行自定义 Prompt 的桌面工具。它同时包含 CLI 与 PySide6 GUI，两者共享同一套核心逻辑，支持批量提取、长文本截断/分块、失败重试、取消与汇总输出。

主要特性
--------
- `.docx` 文本 + 可选表格提取，自动清洗空行。
- 长文本策略：截断 (`truncate`) 或多段分块 (`chunk`)，保证大文档也能被处理。
- Prompt 模板安全渲染 `{filename}/{filepath}/{content}/{meta}`，默认 Prompt 即“严格客观评价 Word 文档质量”模板，为每个 Word 自动生成评分 + 亮点 + 改进建议。
- LLM 请求带指数退避、失败重试，单文件失败不会影响全局。
- 输出 `results/*.md`、`summary.csv`、`run.json` 与完整 `run.log`。
- GUI 支持开始、取消、仅重试失败、打开输出目录等控件。
- 扫描会递归遍历子文件夹，自动跳过 `.doc` 文件并提示“请另存为 docx”，确保批量目录可直接使用。
- 支持批量目录与单个文件两种模式，初学者无需整理目录也可快速处理单篇 Word。
- 默认 Prompt 存放在 `WordBatchAssistant/default_prompt.txt`，GUI 还提供“从文件加载 / 恢复默认”按钮，便于自定义模板。

环境建议
--------
推荐优先使用 Conda 创建隔离环境（例如：`conda create -n wordbatch python=3.11 && conda activate wordbatch`），再安装依赖并运行。若无法联网，可复制已有 Conda 基础环境或手动放置离线包。

快速开始
--------
1. （可选）创建 Conda 环境并激活。
2. 安装依赖：`pip install -r requirements.txt`
3. 可选：复制 `config.example.json` 为 `config.json` 覆盖默认的 endpoint/model/API Key/参数；若想更改全局 Prompt，直接编辑 `WordBatchAssistant/default_prompt.txt`。
4. CLI 跑批：
   ```bash
   python -m WordBatchAssistant.app.cli.run_batch \
      --input_dir path/to/docs \
      --output_dir path/to/outputs \
      --config_file config.json
   ```
   - 如需单文件处理，可改用 `--input_file /path/to/doc.docx`。
   - 若要临时覆盖 Prompt，可追加 `--prompt_file prompt.txt`。
5. GUI：`python -m WordBatchAssistant.app.main`

CLI & GUI 说明
--------------
- CLI 默认把输出写回输入目录（可覆盖 `--output_dir`），支持 `--retry_failed`、`--api_key`、`--input_file` 等参数，日志写入 `输出/logs/run.log`。即便自定义 Prompt 未包含 `{content}`，程序也会自动把原文附在结尾，保证每篇文档都按同一 Prompt 运行。
- GUI 专为零基础用户设计：
  - “批量文件夹 / 单个文件” 两种模式一键切换；
  - 默认 Prompt + 20000/8192 token + 自动日志全部准备好，仅需填 API Key 和选择模型；
  - 提供“从文件加载 Prompt / 恢复默认 / 编辑 Prompt”按钮，提示当前模板来源；
  - 高级参数默认折叠，需要时再展开；
  - 运行完成后可直接点击“打开汇总”查看 summary.csv。
- GUI 运行时会实时显示“总任务/成功/失败/跳过”等统计，并把日志写入 `输出/logs/run.log`，便于定位问题。

配置与 API Key
--------------
- 代码内置默认配置（OpenRouter 免费模型 + 提供的 API Key + “严格评价” Prompt + 输入 20000 / 输出 8192 token 限制），GUI 打开即已填好，可直接运行，仅在需要更换模型或 Key 时手动修改。
- 若需要不同参数/Key，可以在 GUI 内直接修改，或在 CLI 中通过 `--api_key`/`config.json` 覆盖，且仍支持 `APP_API_KEY` 环境变量。

构建
----
使用 PyInstaller：
```
pyinstaller build/pyinstaller.spec
```
生成的 `dist/WordBatchAssistant` 目录压缩后即可分发给 Windows 用户。
