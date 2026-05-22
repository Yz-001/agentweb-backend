# AgentWeb v0.1 后端

AI 网页自动化后端服务 - 极简原型版

## 📦 项目概述

AgentWeb v0.1 是一个极简的 FastAPI 后端，提供 `/api/v1/run` 接口接收自然语言指令，调用 Browser Use 库驱动 Playwright 浏览器执行网页自动化任务，并返回执行结果和日志。

**特点**：
- 无数据库、无用户认证、无缓存
- 同步执行（单一请求阻塞直到任务结束，超时 300 秒）
- 支持 OpenAI 兼容的 API（DeepSeek、通义千问等）
- 标准项目结构，易于扩展

## 🚀 快速开始

### 方式一：Docker Compose（推荐）

```bash
# 构建并启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

服务将在 `http://localhost:8000` 启动。

### 方式二：本地开发

```bash
# 安装依赖（需要 Python 3.11+）
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium

# 启动服务（方式1：使用 Python 模块）
python -m uvicorn app.main:app --reload

# 启动服务（方式2：如果 uvicorn 在 PATH 中）
uvicorn app.main:app --reload
```

## 🌐 访问地址

启动服务后：
- **测试页面**: `http://localhost:8000/test` - 简单的测试界面
- **API 文档**: `http://localhost:8000/docs` - Swagger UI
- **API 文档**: `http://localhost:8000/redoc` - ReDoc

> 💡 **推荐**: 完整的前端应用请访问 [agentweb-frontend](https://github.com/Yz-001/agentweb-frontend) 仓库。

## 📖 API 文档

### 接口说明

#### POST /api/v1/run

执行网页自动化任务。

**请求体**：

```json
{
  "instruction": "打开 https://books.toscrape.com，提取所有图书的标题和价格，最多提取5本",
  "api_key": "sk-你的API Key",
  "base_url": "https://api.openai.com/v1",
  "model_name": "gpt-4o-mini",
  "headless": true,
  "timeout_seconds": 300
}
```

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| instruction | string | 是 | - | 自然语言指令 |
| api_key | string | 是 | - | OpenAI 兼容的 API Key |
| base_url | string | 否 | https://api.openai.com/v1 | API Base URL |
| model_name | string | 否 | gpt-4o-mini | 模型名称 |
| headless | boolean | 否 | true | 是否无头模式运行浏览器 |
| timeout_seconds | integer | 否 | 300 | 任务超时时间（秒） |

**成功响应**：

```json
{
  "success": true,
  "result": {
    "books": [
      {"title": "Book Title 1", "price": "£10.99"},
      {"title": "Book Title 2", "price": "£12.99"}
    ]
  },
  "logs": [
    {
      "step": 1,
      "action": "初始化",
      "description": "正在初始化 Agent...",
      "timestamp": "2026-05-22T12:00:00"
    }
  ],
  "execution_time_ms": 15000,
  "usage": {
    "prompt_tokens": 500,
    "completion_tokens": 200,
    "total_tokens": 700
  }
}
```

#### GET /api/v1/health

健康检查接口。

**响应**：

```json
{
  "status": "ok"
}
```

## 🧪 测试示例

```bash
curl -X POST http://localhost:8000/api/v1/run \
  -H "Content-Type: application/json" \
  -d '{
    "instruction": "打开 https://books.toscrape.com，提取所有图书的标题和价格，最多提取5本",
    "api_key": "sk-你的真实key",
    "model_name": "gpt-4o-mini",
    "headless": true
  }'
```

## 📁 项目结构

```
agentweb-backend/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI 应用入口
│   ├── api/                       # API 路由层
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py          # v1 总路由
│   │       └── endpoints/
│   │           ├── __init__.py
│   │           ├── health.py      # 健康检查接口
│   │           └── run.py         # 任务执行接口
│   ├── core/                      # 核心配置
│   │   ├── __init__.py
│   │   ├── config.py              # 全局配置
│   │   └── exceptions.py          # 自定义异常
│   ├── models/                    # Pydantic 模型
│   │   ├── __init__.py
│   │   └── run.py                 # /run 相关模型
│   ├── services/                  # 业务逻辑层
│   │   ├── __init__.py
│   │   └── agent_executor.py      # Agent 执行服务
│   └── utils/                     # 工具函数
│       ├── __init__.py
│       └── logger.py              # 日志工具
├── static/                        # 静态文件
│   └── index.html                 # 测试页面
├── docs/                          # 文档目录
├── requirements.txt               # Python 依赖
├── Dockerfile                     # Docker 构建文件
├── docker-compose.yml             # Docker Compose 配置
├── .gitignore                     # Git 忽略规则
└── README.md                      # 项目说明
```

## 🔌 浏览器扩展安装（可选）

Browser Use 默认会自动下载浏览器扩展以优化自动化体验。如果网络受限，可以手动预安装：

### 扩展作用

| 扩展名称 | 作用 |
|---------|------|
| uBlock Origin Lite | 广告拦截，减少页面噪音和加载时间 |
| I still don't care about cookies | 自动处理 Cookie 同意弹窗 |
| Force Background Tab | 强制后台打开标签页，优化自动化流程 |

### 手动安装方法

```bash
# 创建扩展目录
mkdir -p ~/.config/browseruse/extensions

# 下载扩展
cd ~/.config/browseruse/extensions

# uBlock Origin Lite
curl -L -o ddkjiahejlhfcafbddmgiahcphecmpfh.crx \
  "https://clients2.google.com/service/update2/crx?response=redirect&prodversion=133&acceptformat=crx3&x=id%3Dddkjiahejlhfcafbddmgiahcphecmpfh%26uc"

# I still don't care about cookies
curl -L -o edibdbjcniadpccecjdfdjjppcpchdlm.crx \
  "https://clients2.google.com/service/update2/crx?response=redirect&prodversion=133&acceptformat=crx3&x=id%3Dedibdbjcniadpccecjdfdjjppcpchdlm%26uc"

# Force Background Tab
curl -L -o gidlfommnbibbmegmgajdbikelkdcmcl.crx \
  "https://clients2.google.com/service/update2/crx?response=redirect&prodversion=133&acceptformat=crx3&x=id%3Dgidlfommnbibbmegmgajdbikelkdcmcl%26uc"

# 解压扩展（.crx 文件实际上是 zip 格式）
for id in ddkjiahejlhfcafbddmgiahcphecmpfh edibdbjcniadpccecjdfdjjppcpchdlm gidlfommnbibbmegmgajdbikelkdcmcl; do
  mkdir -p $id
  unzip -o ${id}.crx -d $id
done
```

### 禁用扩展

如果网络无法下载扩展或不需要扩展功能，可以禁用：

```bash
# 设置环境变量禁用扩展
export BROWSER_USE_DISABLE_EXTENSIONS=1

# 或在启动服务时设置
BROWSER_USE_DISABLE_EXTENSIONS=1 uvicorn app.main:app
```

> 💡 禁用扩展不影响核心功能，只是自动化时可能会遇到广告和 Cookie 弹窗。

## ⚠️ 注意事项

1. **API Key**：需要自备 OpenAI 兼容的 API Key，平台不提供任何 Key。
2. **模型选择**：建议使用支持长输入的模型（如 gpt-4o-mini、deepseek-chat、qwen-max）。部分模型（如 qwen-math-turbo）输入长度限制较低，可能导致执行失败。
3. **执行时间**：任务可能需要较长时间执行，请耐心等待。
4. **并发限制**：v0.1 为原型版，不支持多人同时使用。
5. **错误处理**：如果执行失败，请检查 API Key 是否有效、网络是否通畅、指令是否清晰。

## 🔧 支持的 API 提供商

- OpenAI (GPT-4, GPT-4o, GPT-4o-mini) ✅ **推荐**
- DeepSeek ✅ **推荐**
- 通义千问 (Qwen) ⚠️ 部分模型可能存在兼容性问题
- 任何 OpenAI 兼容的 API

只需在请求中指定对应的 `base_url` 即可。

### ⚠️ 模型兼容性说明

由于 browser-use 对 LLM 的 function calling 格式有严格要求，不同模型的兼容性如下：

| 模型 | 兼容性 | 说明 |
|------|--------|------|
| gpt-4o-mini | ✅ 最佳 | 强烈推荐，性价比高 |
| gpt-4o | ✅ 最佳 | 效果最好，成本较高 |
| deepseek-chat | ✅ 良好 | 国产模型推荐选择 |
| qwen-max | ⚠️ 一般 | 可能遇到格式兼容问题 |
| qwen-turbo/plus | ❌ 较差 | 输入长度限制，不推荐 |
| qwen-math-* | ❌ 不兼容 | 输入长度限制太低 |

**如果遇到验证错误**，请切换到推荐的模型（gpt-4o-mini 或 deepseek-chat）。

## 🔗 相关项目

- **完整前端**: [agentweb-frontend](https://github.com/Yz-001/agentweb-frontend) - React 前端应用

## 🔮 后续扩展规划

- v0.2：用户登录 + SQLite 存储历史任务
- v1.0：工作流编辑器 + 模板管理 + 文件下载
- v1.1：智能缓存 + 定时任务

## 📄 License

MIT