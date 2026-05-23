# AgentWeb v1.0 后端

AI 网页自动化后端服务 - 基于 ReAct 模式的智能 Agent 

**配套前端项目**: [agentweb-frontend](https://github.com/Yz-001/agentweb-frontend)

## 📦 项目概述

AgentWeb v1.0 是一个基于 FastAPI 的 AI 网页自动化后端服务。采用 ReAct (Reasoning + Acting) 模式，结合 OpenAI Function Calling，实现智能化的网页操作。

**特点**：
- ReAct 推理模式，模仿人类思考和行动
- OpenAI Function Calling 提高工具调用准确性
- SSE 实时日志推送，前端实时显示进度
- 浏览器状态持久化，避免重复登录触发验证码
- 支持 OpenAI 兼容的 API（DeepSeek、通义千问等）

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
pip install patchright
patchright install chromium

# 启动服务
python -m uvicorn app.main:app --reload
```

## 🌐 访问地址

启动服务后：
- **Web 界面**: `http://localhost:8000` - 直接在浏览器中操作
- **简单测试**: `http://localhost:8000/test` - 快速测试页面
- **API 文档**: `http://localhost:8000/docs` - Swagger UI
- **API 文档**: `http://localhost:8000/redoc` - ReDoc

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
  "timeout_seconds": 300,
  "allow_manual_login": false
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
| allow_manual_login | boolean | 否 | false | 允许手动处理验证码 |

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
  "logs": [...],
  "execution_time_ms": 15000,
  "usage": {
    "prompt_tokens": 500,
    "completion_tokens": 200,
    "total_tokens": 700
  }
}
```

#### POST /api/v1/run/stream

流式执行任务，SSE 实时推送日志。

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
│   ├── api/v1/
│   │   ├── router.py              # v1 总路由
│   │   └── endpoints/
│   │       ├── health.py          # 健康检查接口
│   │       ├── run.py             # 任务执行接口
│   │       └── stream.py          # SSE 流式执行接口
│   ├── core/
│   │   ├── config.py              # 全局配置
│   │   └── exceptions.py          # 自定义异常
│   ├── models/
│   │   └── run.py                 # /run 相关模型
│   ├── services/
│   │   └── agent_executor.py      # Agent 执行服务（核心）
│   └── utils/
│       └── logger.py              # 日志工具
├── static/
│   └── index.html                 # Web 界面
├── data/browser_state/            # 浏览器状态存储
├── CHANGELOG.md                   # 更新记录
├── requirements.txt               # Python 依赖
├── Dockerfile                     # Docker 构建文件
├── docker-compose.yml             # Docker Compose 配置
└── README.md                      # 项目说明
```

## 🔧 支持的 API 提供商

- OpenAI (GPT-4, GPT-4o, GPT-4o-mini) ✅ **推荐**
- DeepSeek ✅ **推荐**
- 通义千问 (Qwen) ✅ 良好
- 任何 OpenAI 兼容的 API

只需在请求中指定对应的 `base_url` 即可。

## ⚠️ 注意事项

1. **API Key**：需要自备 OpenAI 兼容的 API Key，平台不提供任何 Key。
2. **模型选择**：建议使用 gpt-4o-mini 或 deepseek-chat。
3. **执行时间**：任务可能需要较长时间执行，请耐心等待。
4. **并发限制**：当前版本不支持多人同时使用。

## 🔮 后续扩展规划

- v1.1：任务队列、并发执行
- v1.2：多标签页操作、执行回放
- v2.0：本地模型支持、可视化编辑器

详见 [CHANGELOG.md](CHANGELOG.md)

##  License

MIT License

## 💡 使用建议

**推荐在本地环境运行**，以获得最佳体验：
- 本地运行无需配置 CORS 和身份认证
- 非无头模式可以实时查看浏览器操作
- API Key 仅存储在本地浏览器，安全可控

如需部署到服务器，建议：
- 配置 HTTPS 保护 API Key 传输
- 限制 CORS 允许的域名
- 添加 API 访问认证

## 📝 说明

本项目仅供学习研究使用，请合理合规使用。使用者需自行承担使用责任。
