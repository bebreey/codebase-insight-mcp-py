# codebase-insight-mcp-py

[![CI](https://github.com/bebreey/codebase-insight-mcp-py/actions/workflows/ci.yml/badge.svg)](https://github.com/bebreey/codebase-insight-mcp-py/actions/workflows/ci.yml)

一个**完全离线、零 API Key、只读**的 MCP Server，用 5 个工具让 AI Agent 快速读懂任意本地代码库。

| | |
| --- | --- |
| **离线** | 不联网、不需要任何凭据，内网 / 隔离环境可直接用 |
| **只读** | 所有工具声明 `read_only_hint: true`，不写一个字节；支持目录白名单 |
| **精准** | Python 符号用标准库 `ast` 真解析；TOML 用 `tomllib` 真解析；`.gitignore` 用 `pathspec` 真支持 |
| **结构化** | 每个工具的**返回类型注解即 output_schema**，输出经 Pydantic 校验后同时给出文本与结构化内容 |
| **不崩** | 缺 git、空仓库、无权限、路径不存在，全部降级成可读结论而非异常 |

---

## 快速开始

```bash
git clone https://github.com/bebreey/codebase-insight-mcp-py.git
cd codebase-insight-mcp-py
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e ".[dev]"
```

运行：

```bash
python -m codebase_insight           # 作为 stdio MCP server 启动
python -m codebase_insight --help    # 帮助与全部环境变量
python -m codebase_insight --list-tools
```

开发命令：

| 命令 | 作用 |
| --- | --- |
| `pytest` | 运行测试（151 个） |
| `pytest --cov` | 运行测试并输出覆盖率 |
| `ruff check .` | 静态检查 |
| `ruff format .` | 格式化 |
| `mypy` | 严格类型检查（`strict = true`） |
| `python scripts/demo.py` | 起真实 MCP 会话，调用全部 5 个工具并打印结果 |

---

## 接入 MCP 客户端

```json
{
  "mcpServers": {
    "codebase-insight-py": {
      "command": "/absolute/path/to/codebase-insight-mcp-py/.venv/bin/codebase-insight-mcp-py",
      "env": {
        "CBI_DEFAULT_ROOT": "/absolute/path/to/your/project"
      }
    }
  }
}
```

Windows 下 `command` 填 `.venv\\Scripts\\codebase-insight-mcp-py.exe`。

| 客户端 | 配置文件位置 |
| --- | --- |
| Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json`（macOS）<br>`%APPDATA%\Claude\claude_desktop_config.json`（Windows） |
| Cursor | 项目内 `.cursor/mcp.json` 或全局 `~/.cursor/mcp.json` |
| 其他 | 任何支持 stdio transport 的 MCP 客户端，JSON 格式相同 |

---

## 工具

| 工具 | 用途 |
| --- | --- |
| `repo_overview` | 项目类型、语言占比、代码行数、入口点、构建与测试命令、最大文件 |
| `find_todos` | TODO / FIXME / HACK / BUG 等技术债标记，带 owner，按严重度排序 |
| `search_symbols` | 定位函数 / 类 / 方法 / 接口等声明，支持 16 种语言 |
| `audit_dependencies` | 依赖清单与版本锁定审计，覆盖 pyproject / requirements / npm / cargo / go |
| `assess_health` | 9 项加权评分 + 具体待办 + 脱敏凭据检查 |

推荐调用顺序：

```text
repo_overview → find_todos → search_symbols → audit_dependencies → assess_health
```

---

## 配置

全部通过环境变量：

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `CBI_DEFAULT_ROOT` | 进程工作目录 | 工具调用省略 `path` 时分析的目录 |
| `CBI_ROOTS` | 未设置（不限制） | 目录白名单，`,` 或 `;` 分隔；设置后越界路径直接拒绝 |
| `CBI_MAX_FILES` | `20000` | 单次遍历的文件数上限 |
| `CBI_MAX_DEPTH` | `12` | 目录递归深度上限 |
| `CBI_MAX_FILE_BYTES` | `2097152` | 参与文本分析的单文件大小上限 |
| `CBI_DEBUG` | 未设置 | 设为 `1` 在 **stderr** 输出诊断日志 |

> `stdout` 是 JSON-RPC 通道，所有诊断信息只走 stderr。

---

## License

[MIT](LICENSE)
