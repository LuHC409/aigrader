
---

# WordBatchAssistant 工程设计文档（方案 A 最终版）

## 0. 项目目标与交付标准

### 0.1 目标（可交付给 Windows 家用）

* Windows：**解压 zip → 双击 exe → 选择文件夹 → 批量处理 Word(.docx) → 输出结果**
* 输入：文件夹内多个 `.docx`
* 提取：Word 正文纯文本（MVP），可选包含表格文本
* 推理：UI 自定义 Prompt（模板变量），调用你的 LLM API
* 输出：每个文件一份结果（`.md` / `.txt`）+ `summary.csv` + `run.log`
* 稳定性：支持取消、失败不中断、失败重试、限流退避
* 免环境：妈妈电脑无需安装 Python/依赖，解压即用

### 0.2 明确不做（减少风险）

* 不支持 `.doc`（老格式）；检测到则 `skipped` 并提示“请另存为 docx”
* 不提取图片、批注、修订记录
* 不还原富文本，只输出纯文本

---

## 1. 技术栈与核心选择

* GUI：PySide6
* Word 解析：python-docx
* HTTP：requests
* 打包：PyInstaller（在 Windows 环境构建）
* 日志：标准 logging
* 汇总：csv + json

关键原则：

* UI 与核心逻辑解耦（核心 `core/` 可在 CLI/测试直接跑）
* 所有耗时操作不阻塞 UI（子线程）
* 取消可用（cancel_event）
* 单文件失败不影响全局

---

## 2. 目录结构（含你要求的 test 文件夹）

```
WordBatchAssistant/
  app/
    main.py
    ui/
      main_window.py
      models.py
      widgets.py
    core/
      config.py
      docx_extract.py
      prompt_render.py
      chunking.py
      llm_client.py
      runner.py
      output_writer.py
      logging_utils.py
      types.py
    cli/
      run_batch.py
  test/                     <- 必须新建（本地先跑通要求）
    fixtures/
      input_docs/           <- 放测试 docx
      outputs/              <- 测试输出（git 忽略）
    test_config.json
    test_prompt.txt
    smoke_test.py
    fake_llm_server.py (可选)
  build/
    pyinstaller.spec
  .github/
    workflows/
      build-windows.yml
  requirements.txt
  requirements-build.txt
  README.txt
  config.example.json
  .gitignore
```

---

## 3. 功能规格（用户视角）

### 3.1 主界面（必须）

1. 输入文件夹（选择）
2. 输出文件夹（选择；默认：输入目录下 `_outputs_YYYYMMDD_HHMMSS`）
3. Prompt 多行编辑框
4. API Key 输入框（可显示/隐藏）
5. 模型参数：endpoint、model、temperature、max_output_tokens、timeout_sec
6. 处理策略：

   * long_doc_mode：`truncate` 或 `chunk`
   * max_input_tokens（截断阈值）
   * chunk_target_tokens（分块目标）
   * 并发数 concurrency（默认 2）
   * include_tables（是否提取表格）
7. 控制按钮：开始、取消、仅重试失败、打开输出文件夹
8. 进度条 + 文件列表（状态/耗时/输出路径/错误）
9. 日志窗口

### 3.2 Prompt 模板变量（必须）

* `{filename}`：文件名
* `{filepath}`：完整路径（可选）
* `{content}`：提取后的文本（经截断/分块策略处理）
* `{meta}`：元信息 JSON 字符串（字数、段落数、表格数、是否截断等）

渲染规则：

* 仅安全替换，不允许 eval
* 出现未知变量：阻止开始并提示

---

## 4. 数据与流程（系统视角）

数据流：
`扫描文件夹 → 生成 TaskItem 列表 → 对每个 docx 提取文本+meta → 长文本策略 → 渲染 prompt → 调用 LLM → 写结果 → 更新 summary.csv`

状态机（每文件）：
`pending → running → success/failed/skipped/cancelled`

---

## 5. 核心类型定义（types.py）

建议 dataclass：

* `AppConfig`

  * endpoint, model, temperature, max_output_tokens, timeout_sec
  * concurrency, include_tables
  * long_doc_mode, max_input_tokens, chunk_target_tokens
* `DocMeta`

  * paragraph_count, table_count, char_count, token_est
  * was_truncated(bool), chunk_count(int)
* `TaskItem`

  * filepath, filename, output_path
  * status, error_message
* `TaskResult`

  * status, elapsed_sec, output_path, error_message
  * input_chars, input_tokens_est, mode, usage(optional)

---

## 6. Word 提取（docx_extract.py）

### 6.1 只支持 docx

* 后缀不是 `.docx`：`skipped`
* `.doc`：`skipped` 并提示另存为 docx

### 6.2 提取规则

* paragraphs：按顺序读取
* tables（可选）：按行拼接为 `| cell1 | cell2 |`
* 文本清洗：

  * strip 每段
  * 连续空行最多保留 1 行
  * 输出 `\n` 统一

输出：

* `text: str`
* `meta: DocMeta`（至少包含段落数、表格数、char_count）

---

## 7. 长文档策略（chunking.py）

### 7.1 token 粗估（MVP）

`token_est = ceil(len(text) / 4)`

### 7.2 truncate 模式（默认）

* 若 token_est > max_input_tokens：

  * 取前 70% + 后 30%
  * meta.was_truncated = true
* 否则原文

### 7.3 chunk 模式（建议交付版也支持）

* 按段落累积，达到 chunk_target_tokens 附近切块
* 每块调用一次 LLM 得 chunk_result
* 再对 chunk_result 做最终汇总生成 final_result
* meta.chunk_count = 块数

---

## 8. Prompt 渲染（prompt_render.py）

输入：`template: str`, `vars: dict`
输出：`rendered_prompt: str`

规则：

* 只允许替换 `{filename}{filepath}{content}{meta}`
* 未定义变量 -> 抛出明确异常（UI/CLI 捕获后提示）

---

## 9. LLM 调用（llm_client.py）

### 9.1 统一接口（必须）

* `LLMClient.generate(prompt: str) -> LLMResponse`

  * `LLMResponse.text`
  * `LLMResponse.usage`（可选）
  * `LLMResponse.raw`（可选）

### 9.2 重试策略（必须）

* 429：指数退避 1/2/4/8/16/32（最多 6 次）+ 小抖动
* 5xx：最多 4 次
* timeout：最多 3 次
* 4xx(401/403/400)：不重试，直接失败

---

## 10. Runner：并发、取消、失败隔离（runner.py）

### 10.1 运行流程（伪代码）

* scan_folder -> tasks
* for task in tasks: submit to threadpool（受 concurrency 限制）
* 每 task：

  * check cancel_event
  * extract docx
  * apply chunk/truncate
  * render prompt
  * call LLM（含重试）
  * write output
  * update summary row

### 10.2 取消机制

* UI/CLI 触发 `cancel_event.set()`
* 各阶段检查 `cancel_event.is_set()`
* 已开始的网络请求可等超时后退出（或在 requests 侧缩短 timeout）

---

## 11. 输出规范（output_writer.py）

输出根目录结构：

```
outputs/
  results/
  logs/
  summary.csv
  run.json
```

单文件输出命名：

* `results/{原文件名}.md`

summary.csv 字段（固定）：

* filename, filepath, status, elapsed_sec
* input_chars, input_tokens_est
* mode, output_path, error_message

run.json：

* start_time/end_time
* config（不含明文 api_key）
* total/success/failed/skipped/cancelled

日志：

* `logs/run.log`（详细）

---

## 12. 配置管理（config.py）

config.example.json（不含 key）：

```json
{
  "endpoint": "https://your-endpoint",
  "model": "your-model",
  "temperature": 0.2,
  "max_output_tokens": 800,
  "timeout_sec": 120,
  "concurrency": 2,
  "include_tables": true,
  "long_doc_mode": "truncate",
  "max_input_tokens": 3000,
  "chunk_target_tokens": 1200
}
```

API key：

* 默认 UI 输入，不落盘（最安全）
* 本地测试可通过环境变量 `APP_API_KEY` 注入（见 test 部分）

---

## 13. 本地先跑通要求（你提出的新增要求，必须执行）

### 13.1 目的

在你开始做 GUI / 打包之前，先证明以下链路全部 OK：

* 能扫描文件夹
* 能读 docx 并提取文本
* 能渲染 prompt
* 能调用一个“可控”的 LLM（先用 fake，避免浪费/避免接口问题）
* 能写输出与 summary.csv

### 13.2 必须新建 `test/` 文件夹（结构见第 2 节）

并提供以下文件：

#### A) `test/fixtures/input_docs/`

放 2~5 个 docx：

* `short.docx`（几段文字）
* `table.docx`（带表格）
* `long.docx`（复制粘贴多段，触发截断/分块）
* （可选）混入一个 `not_docx.txt` 用于跳过测试

#### B) `test/test_prompt.txt`

内容示例（你可改）：

```
你是一个文档助手。请阅读以下 Word 内容并给出要点总结（5条以内）。
文件名：{filename}
元信息：{meta}
正文：
{content}
```

#### C) `test/test_config.json`

用于本地 smoke test，endpoint 指向 fake server 或 mock：

```json
{
  "endpoint": "http://127.0.0.1:8089/generate",
  "model": "fake",
  "temperature": 0,
  "max_output_tokens": 300,
  "timeout_sec": 30,
  "concurrency": 2,
  "include_tables": true,
  "long_doc_mode": "truncate",
  "max_input_tokens": 1200,
  "chunk_target_tokens": 600
}
```

#### D) `test/fake_llm_server.py`（推荐，确保完全可控）

* 起一个本地 HTTP 服务，收到 prompt 后返回固定 JSON：

  * `text = "FAKE_RESPONSE: " + prompt 前 200 字`
* 好处：你不需要真实 API 就能跑通全链路

#### E) `test/smoke_test.py`（必须）

* 自动化运行一次批处理：

  * 输入目录：`test/fixtures/input_docs`
  * 输出目录：`test/fixtures/outputs/run_{timestamp}`
  * 读取 `test_prompt.txt`
  * 读取 `test_config.json`
* 验收条件（smoke test 断言）：

  * outputs/results 下生成与 docx 数量相同的 `.md`
  * summary.csv 存在且行数正确
  * 任意失败都要在 summary.csv 里出现错误信息而不是直接崩溃退出
  * long.docx 能触发 `was_truncated=true`（或 chunk_count>1）

### 13.3 本地先跑通的执行命令（规范化）

你需要提供一个 CLI 入口（app/cli/run_batch.py），这样你在 Mac 上先跑通：

1. 启动 fake server（一个终端）
   `python test/fake_llm_server.py`

2. 跑 smoke test（另一个终端）
   `python test/smoke_test.py`

> 只有当这两步全绿，你才开始做 GUI 和打包。

---

## 14. CLI 入口（app/cli/run_batch.py）

必须支持参数：

* `--input_dir`
* `--output_dir`
* `--prompt_file`
* `--config_file`

用于测试与调试，GUI 只是调用同一套 core。

---

## 15. GUI 实现细节（ui/）

* UI 只负责：

  * 读取用户输入
  * 组装 AppConfig
  * 调用 Runner（线程池）
  * 监听 signals 更新表格/进度/日志
* Runner/core 不得 import UI 模块（防止循环依赖）

---

## 16. 打包（PyInstaller + GitHub Actions）

### 16.1 打包形态

* 推荐 `onedir`
* 交付 zip：`dist/WordBatchAssistant/` 压缩

### 16.2 Windows 构建方式（你 Mac 开发的关键）

* GitHub Actions windows runner 构建 exe
* artifact 下载后发给妈妈

工作流步骤：

1. setup python
2. pip install -r requirements.txt
3. pip install -r requirements-build.txt
4. pyinstaller build/pyinstaller.spec
5. copy README/config.example.json to dist
6. zip dist
7. upload artifact

---

## 17. requirements

`requirements.txt`（运行依赖）：

* PySide6
* python-docx
* requests

`requirements-build.txt`（构建依赖）：

* pyinstaller

---

## 18. 交付前测试清单（必须）

### 本地 smoke test（第 13 节）必须通过

### Windows 实机验证（必须至少一次）

* 解压 zip
* 双击 exe 启动
* 选择测试 docx 文件夹
* 生成 outputs 与 summary.csv
* 取消按钮可用
* 失败提示清晰

---

## 19. 你需要自己填的唯一平台相关点

我的api key是：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
prompt 就是评价word，test文件夹已经创建好了
---

如果你现在要继续推进到“可直接开工的程度”，我可以在同一套结构下**把所有文件的代码骨架 + fake server + smoke test + CLI + GitHub Actions + spec**一次性给你（你只要填你的真实 API 解析部分即可）。你只需回一句：**“生成骨架代码（含 test）”**。
