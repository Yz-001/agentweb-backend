# 更新记录 (Changelog)

所有重要的更改都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [v1.0.0] - 2026-05-23

### 首次发布

### ✨ 新增功能

#### 核心功能
- **ReAct 模式 AI 推理引擎** - 采用 Thought → Action → Observation 循环模式，模仿人类思考和行动过程
- **OpenAI Function Calling 支持** - 使用 Function Calling 提高工具调用的准确性和可靠性
- **多模型兼容** - 支持 OpenAI、DeepSeek、通义千问等 OpenAI 兼容接口

#### 浏览器自动化工具
- `goto(url)` - 导航到指定 URL
- `input(selector, value, press_enter)` - 在输入框输入文本，支持按 Enter 提交
- `click(selector|text)` - 点击页面元素，支持 CSS 选择器或文本匹配
- `scroll(direction)` - 页面滚动（向上/向下）
- `wait(seconds)` - 等待指定时间
- `extract()` - 从页面提取结构化数据
- `done(result, summary)` - 标记任务完成并返回结果

#### 智能特性
- **浏览器状态持久化** - 自动保存和加载 Cookies，避免重复登录触发验证码
- **弹窗自动处理** - 自动检测和关闭页面弹窗/遮罩层
- **手动登录支持** - 非无头模式下检测到验证码时等待用户手动处理
- **多模态理解** - 支持截图 + 文本混合输入，AI 可视化理解页面
- **智能错误恢复** - 连续错误时自动尝试其他方案或提取数据结束

#### 实时日志系统
- **SSE (Server-Sent Events)** - 实时推送执行日志，无需等待任务完成
- **心跳保持连接** - 每秒发送心跳，防止连接中断
- **实时状态显示** - 前端实时显示思考、执行、结果

#### Web 界面
- **美观的交互界面** - 左侧输入指令，右侧实时日志和结果
- **API 配置弹窗** - 配置 API Key、Base URL、模型名称等
- **配置持久化** - 使用 LocalStorage 保存配置
- **快捷键支持** - Ctrl+Enter 快速执行任务

### 🔧 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/health` | GET | 健康检查 |
| `/api/v1/run` | POST | 同步执行任务 |
| `/api/v1/run/stream` | POST | 流式执行任务（SSE 实时日志） |

### 📦 技术栈

- **后端**: FastAPI + LangChain + Playwright (Patchright)
- **前端**: 纯 HTML/CSS/JavaScript（无需构建）
- **AI**: OpenAI API 兼容接口

### 🛡️ 安全特性

- API Key 仅在请求时传递，不在服务器存储
- 浏览器 Cookies 加密存储在本地
- 支持自定义 Base URL（数据不出境）

### 📝 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `model_name` | gpt-4o-mini | 模型名称 |
| `headless` | true | 无头模式 |
| `timeout_seconds` | 300 | 任务超时时间 |
| `allow_manual_login` | false | 允许手动处理验证码 |
| `max_steps` | 20 | 最大推理步数 |

---

## 使用示例

```json
{
  "instruction": "打开百度搜索今日热搜前3条",
  "api_key": "sk-xxx",
  "model_name": "gpt-4o-mini",
  "headless": true
}
```

**返回结果**:
```json
{
  "success": true,
  "result": {
    "热搜1": "中俄关系迈上新起点",
    "热搜2": "中国香港航天员首上太空",
    "热搜3": "烟台老人的纯手工蓑衣火了"
  },
  "logs": [...],
  "execution_time_ms": 15000,
  "usage": {"total_tokens": 2000}
}
```

---

## 未来计划 (Roadmap)

### v1.1 计划
- [ ] 支持更多浏览器操作（拖拽、悬停、双击）
- [ ] 添加任务队列和并发执行
- [ ] 支持自定义工具扩展

### v1.2 计划
- [ ] 支持多页面/标签页操作
- [ ] 添加执行回放功能
- [ ] 支持导出执行脚本

### v2.0 计划
- [ ] 支持本地模型（Ollama）
- [ ] 添加可视化流程编辑器
- [ ] 支持团队协作和任务分享

---

## 致谢

感谢以下开源项目：
- [LangChain](https://github.com/langchain-ai/langchain) - AI 应用开发框架
- [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python) - 浏览器自动化（Playwright 反检测版本）
- [FastAPI](https://github.com/tiangolo/fastapi) - 高性能 Web 框架