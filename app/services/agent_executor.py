"""
Agent 执行服务 - 使用 LangChain + Playwright 实现
采用 ReAct (Reasoning + Acting) 模式 + OpenAI Function Calling
支持浏览器状态持久化，避免触发验证码
"""
import asyncio
import json
import re
import time
import sys
import pathlib
from typing import Dict, Any, List
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

# 设置 UTF-8 编码
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from patchright.async_api import async_playwright
import base64

from app.models.run import LogEntry
from app.core.exceptions import InvalidAPIKeyError, ExecutionError, TimeoutError
from app.utils.logger import logger, log_step

# 浏览器状态文件目录
STATE_DIR = pathlib.Path("data/browser_state")


# ============================================================================
# 工具抽象层 - Tool Definition
# ============================================================================

@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    output: str
    error: str = ""
    data: Dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    """工具基类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称"""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述"""
        pass
    
    @property
    def parameters(self) -> Dict[str, Any]:
        """工具参数 schema (JSON Schema 格式)"""
        return {
            "type": "object",
            "properties": {},
            "required": []
        }
    
    @abstractmethod
    async def execute(self, page, **params) -> ToolResult:
        """执行工具"""
        pass
    
    def to_function_schema(self) -> Dict[str, Any]:
        """转换为 OpenAI Function Calling 格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
            }
        }


class GotoTool(BaseTool):
    """导航到 URL"""
    
    def __init__(self, timeout: int = 60000, wait_after: float = 2.0):
        self.timeout = timeout
        self.wait_after = wait_after
    
    @property
    def name(self) -> str:
        return "goto"
    
    @property
    def description(self) -> str:
        return "导航到指定的 URL 地址。用于打开网页或跳转到新页面。"
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要导航到的完整 URL，例如 https://www.example.com"
                }
            },
            "required": ["url"]
        }
    
    async def execute(self, page, url: str, **kwargs) -> ToolResult:
        try:
            await page.goto(url, timeout=self.timeout, wait_until="domcontentloaded")
            await asyncio.sleep(self.wait_after)
            return ToolResult(
                success=True,
                output=f"成功导航到 {url}，当前页面标题: {await page.title()}",
                data={"url": page.url, "title": await page.title()}
            )
        except Exception as e:
            logger.warning(f"GotoTool 执行失败: {str(e)}")
            return ToolResult(success=False, output="", error=str(e))


class InputTool(BaseTool):
    """在输入框中输入文本"""
    
    def __init__(self, timeout: int = 5000, wait_after: float = 0.5, keyboard_delay: int = 50, wait_after_search: float = 3.0):
        self.timeout = timeout
        self.wait_after = wait_after
        self.keyboard_delay = keyboard_delay
        self.wait_after_search = wait_after_search
    
    @property
    def name(self) -> str:
        return "input"
    
    @property
    def description(self) -> str:
        return "在指定的输入框中输入文本内容。用于填写表单、搜索框等。"
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS 选择器或 nth(索引) 格式，例如 'input[name=\"q\"]' 或 'nth(0)'"
                },
                "value": {
                    "type": "string",
                    "description": "要输入的文本内容"
                },
                "press_enter": {
                    "type": "boolean",
                    "description": "输入完成后是否按 Enter 键（用于搜索）"
                }
            },
            "required": ["selector", "value"]
        }
    
    async def execute(self, page, selector: str, value: str, press_enter: bool = False, **kwargs) -> ToolResult:
        # 参数验证
        if not selector:
            return ToolResult(success=False, output="", error="selector 参数不能为空")
        if not value:
            return ToolResult(success=False, output="", error="value 参数不能为空")
        
        try:
            # 处理 nth(索引) 格式
            if selector.startswith("nth("):
                try:
                    idx = int(selector.replace("nth(", "").replace(")", ""))
                except ValueError:
                    return ToolResult(success=False, output="", error=f"无效的 nth 格式: {selector}")
                
                inputs = await page.locator("input:visible, textarea:visible").all()
                if idx < 0 or idx >= len(inputs):
                    return ToolResult(success=False, output="", error=f"索引 {idx} 超出范围，当前共有 {len(inputs)} 个输入框")
                await inputs[idx].fill(value, timeout=self.timeout)
            else:
                await page.locator(selector).first.fill(value, timeout=self.timeout)
            
            await asyncio.sleep(self.wait_after)
            
            if press_enter:
                await page.keyboard.press("Enter")
                await asyncio.sleep(self.wait_after_search)
                return ToolResult(
                    success=True,
                    output=f"输入 '{value}' 并按 Enter，当前 URL: {page.url}",
                    data={"value": value, "submitted": True}
                )
            
            return ToolResult(success=True, output=f"成功输入: {value}", data={"value": value})
        except Exception as e:
            logger.warning(f"InputTool fill 失败: {str(e)}，尝试键盘输入")
            # 降级：使用键盘输入
            try:
                await page.keyboard.type(value, delay=self.keyboard_delay)
                if press_enter:
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(self.wait_after_search)
                return ToolResult(success=True, output=f"使用键盘输入: {value}")
            except Exception as e2:
                logger.error(f"InputTool 键盘输入也失败: {str(e2)}")
                return ToolResult(success=False, output="", error=str(e2))


class ClickTool(BaseTool):
    """点击页面元素"""
    
    def __init__(self, timeout: int = 5000, wait_after: float = 1.0):
        self.timeout = timeout
        self.wait_after = wait_after
    
    @property
    def name(self) -> str:
        return "click"
    
    @property
    def description(self) -> str:
        return "点击页面上的元素，如按钮、链接等。可以通过选择器或文本内容定位元素。"
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS 选择器，例如 'button.submit' 或 'nth(2)'"
                },
                "text": {
                    "type": "string",
                    "description": "要点击元素包含的文本内容（优先使用，更可靠）"
                }
            },
            "required": []
        }
    
    async def execute(self, page, selector: str = "", text: str = "", **kwargs) -> ToolResult:
        # 参数验证
        if not selector and not text:
            return ToolResult(success=False, output="", error="必须提供 selector 或 text 参数")
        
        url_before = page.url
        try:
            # 优先使用文本匹配
            if text:
                for element_type in ["button:visible", "a:visible", "[role='button']:visible", "div:visible", "span:visible", "input:visible"]:
                    try:
                        locator = page.locator(element_type).filter(has_text=text).first
                        if await locator.is_visible(timeout=1000):
                            await locator.click(timeout=self.timeout)
                            await asyncio.sleep(self.wait_after)
                            url_after = page.url
                            if url_after != url_before:
                                return ToolResult(
                                    success=True,
                                    output=f"点击包含 '{text}' 的元素成功，页面跳转到: {url_after}",
                                    data={"clicked": text, "navigated": True, "new_url": url_after}
                                )
                            return ToolResult(success=True, output=f"点击包含 '{text}' 的元素成功")
                    except Exception as e:
                        logger.debug(f"ClickTool 尝试 {element_type} 失败: {str(e)}")
                        continue
                
                # 尝试点击任意包含文本的可点击元素
                try:
                    locator = page.get_by_text(text, exact=False).first
                    await locator.click(timeout=self.timeout)
                    await asyncio.sleep(self.wait_after)
                    return ToolResult(success=True, output=f"点击文本 '{text}' 成功")
                except Exception as e:
                    logger.warning(f"ClickTool 文本点击失败: {str(e)}")
            
            # 使用选择器
            if selector:
                if selector.startswith("nth("):
                    try:
                        idx = int(selector.replace("nth(", "").replace(")", ""))
                    except ValueError:
                        return ToolResult(success=False, output="", error=f"无效的 nth 格式: {selector}")
                    
                    # 获取所有可见且在视口内的可点击元素
                    all_clickable = await page.locator("button:visible, a:visible, [role='button']:visible, input[type='button']:visible, input[type='submit']:visible").all()
                    
                    # 过滤：只保留在视口内的元素
                    clickable = []
                    for el in all_clickable:
                        try:
                            is_visible = await el.is_visible()
                            if is_visible:
                                box = await el.bounding_box()
                                if box and box['y'] >= 0 and box['y'] <= page.viewport_size['height']:
                                    clickable.append(el)
                        except:
                            continue
                    
                    if idx < 0 or idx >= len(clickable):
                        return ToolResult(success=False, output="", error=f"索引 {idx} 超出范围，视口内共有 {len(clickable)} 个可点击元素（总元素 {len(all_clickable)} 个，部分在视口外）")
                    await clickable[idx].click()
                    await asyncio.sleep(self.wait_after)
                    return ToolResult(success=True, output=f"点击第 {idx} 个可点击元素成功")
                else:
                    await page.locator(selector).first.click(timeout=self.timeout)
                    await asyncio.sleep(self.wait_after)
                    return ToolResult(success=True, output=f"点击选择器 '{selector}' 成功")
            
        except Exception as e:
            logger.warning(f"ClickTool 执行失败: {str(e)}，尝试按 Enter")
            # 降级：按 Enter
            try:
                await page.keyboard.press("Enter")
                await asyncio.sleep(self.wait_after)
                return ToolResult(success=True, output="按 Enter 键代替点击")
            except Exception as e2:
                logger.error(f"ClickTool Enter 也失败: {str(e2)}")
                return ToolResult(success=False, output="", error=str(e))


class ScrollTool(BaseTool):
    """滚动页面"""
    
    def __init__(self, distance: int = 500, wait_after: float = 1.0):
        self.distance = distance
        self.wait_after = wait_after
    
    @property
    def name(self) -> str:
        return "scroll"
    
    @property
    def description(self) -> str:
        return "滚动页面以查看更多内容。可以向上或向下滚动。"
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["down", "up"],
                    "description": "滚动方向，down 为向下，up 为向上"
                },
                "distance": {
                    "type": "integer",
                    "description": f"滚动距离（像素），默认 {self.distance}"
                }
            },
            "required": ["direction"]
        }
    
    async def execute(self, page, direction: str = "down", distance: int = None, **kwargs) -> ToolResult:
        # 参数验证
        if direction not in ["down", "up"]:
            return ToolResult(success=False, output="", error=f"无效的滚动方向: {direction}，必须是 'down' 或 'up'")
        
        try:
            dist = distance or self.distance
            if direction == "up":
                dist = -dist
            await page.evaluate(f"window.scrollBy(0, {dist})")
            await asyncio.sleep(self.wait_after)
            return ToolResult(success=True, output=f"向{direction}滚动 {abs(dist)} 像素")
        except Exception as e:
            logger.warning(f"ScrollTool 执行失败: {str(e)}")
            return ToolResult(success=False, output="", error=str(e))


class WaitTool(BaseTool):
    """等待指定时间"""
    
    @property
    def name(self) -> str:
        return "wait"
    
    @property
    def description(self) -> str:
        return "等待指定的秒数。用于等待页面加载、动画完成等。"
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "number",
                    "description": "等待的秒数，默认 2 秒"
                }
            },
            "required": []
        }
    
    async def execute(self, page, seconds: float = 2.0, **kwargs) -> ToolResult:
        # 参数验证
        if seconds < 0:
            return ToolResult(success=False, output="", error="等待时间不能为负数")
        if seconds > 60:
            logger.warning(f"等待时间 {seconds} 秒较长，可能影响性能")
        
        try:
            await asyncio.sleep(seconds)
            return ToolResult(success=True, output=f"等待了 {seconds} 秒")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


class ExtractTool(BaseTool):
    """从页面提取数据"""
    
    def __init__(self, extract_text_length: int = 1500):
        self.extract_text_length = extract_text_length
    
    @property
    def name(self) -> str:
        return "extract"
    
    @property
    def description(self) -> str:
        return "从当前页面提取结构化数据。用于获取页面内容、商品信息、搜索结果等。"
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要提取的字段名称列表，例如 ['title', 'price', 'description']"
                }
            },
            "required": []
        }
    
    async def execute(self, page, fields: List[str] = None, **kwargs) -> ToolResult:
        try:
            page_text = await page.evaluate("() => document.body.innerText")
            page_url = page.url
            page_title = await page.title()
            
            return ToolResult(
                success=True,
                output=f"成功提取页面数据，URL: {page_url}",
                data={
                    "url": page_url,
                    "title": page_title,
                    "content": page_text[:self.extract_text_length],
                    "fields": fields
                }
            )
        except Exception as e:
            logger.warning(f"ExtractTool 执行失败: {str(e)}")
            return ToolResult(success=False, output="", error=str(e))


class DoneTool(BaseTool):
    """标记任务完成"""
    
    @property
    def name(self) -> str:
        return "done"
    
    @property
    def description(self) -> str:
        return "标记任务已完成，并返回最终结果。当任务目标已达成时使用此工具。"
    
    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "result": {
                    "type": "object",
                    "description": "任务执行结果，包含提取的数据或完成状态"
                },
                "summary": {
                    "type": "string",
                    "description": "任务完成的简要说明"
                }
            },
            "required": ["summary"]
        }
    
    async def execute(self, page, result: Dict = None, summary: str = "", **kwargs) -> ToolResult:
        return ToolResult(
            success=True,
            output=f"任务完成: {summary}",
            data={"result": result or {}, "summary": summary, "done": True}
        )


# ============================================================================
# Agent 执行器 - ReAct 模式实现
# ============================================================================

class AgentExecutor:
    """Agent 执行器 - 采用 ReAct (Reasoning + Acting) 模式
    
    支持 OpenAI Function Calling 提高可靠性
    支持实时日志回调
    """
    
    SYSTEM_PROMPT = """你是网页操作Agent。工具: goto(url), input(selector,value,press_enter), click(selector|text), scroll(dir), wait(sec), extract(), done(result,summary)。

规则:
1. 优先用 click(text="按钮文字") 点击
2. nth(索引)从0开始，先看元素列表确认索引
3. 失败后换方法，不重复相同操作
4. 任务完成用 done 返回结果

决策格式: {"thought":"状态→差距→动作→预期", "action":"工具名", "params":{}}

思考示例: "当前在搜索页，需输入关键词→输入框nth(0)→输入'xxx'并回车→跳转结果页"
"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model_name: str = "gpt-4o-mini",
        headless: bool = True,
        max_steps: int = 20,
        page_timeout: int = 60000,
        element_timeout: int = 5000,
        max_elements: int = 15,
        wait_after_navigate: float = 2.0,
        wait_after_action: float = 0.5,
        wait_after_search: float = 3.0,
        wait_after_scroll: float = 1.0,
        wait_after_click: float = 1.0,
        manual_login_timeout: int = 60,
        scroll_distance: int = 500,
        keyboard_delay: int = 50,
        extract_text_length: int = 1500,
        snippet_length: int = 500,
        element_text_length: int = 30,
        max_history_messages: int = 30,
        use_function_calling: bool = True,
        log_callback = None  # 实时日志回调函数
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.headless = headless
        self.logs: List[LogEntry] = []
        self._llm = None
        
        # 配置参数
        self.max_steps = max_steps
        self.page_timeout = page_timeout
        self.element_timeout = element_timeout
        self.max_elements = max_elements
        self.wait_after_navigate = wait_after_navigate
        self.wait_after_action = wait_after_action
        self.wait_after_search = wait_after_search
        self.wait_after_scroll = wait_after_scroll
        self.wait_after_click = wait_after_click
        self.manual_login_timeout = manual_login_timeout
        self.scroll_distance = scroll_distance
        self.keyboard_delay = keyboard_delay
        self.extract_text_length = extract_text_length
        self.snippet_length = snippet_length
        self.element_text_length = element_text_length
        self.max_history_messages = max_history_messages
        self.use_function_calling = use_function_calling
        self.log_callback = log_callback  # 保存回调函数
        
        # 初始化工具集
        self.tools: Dict[str, BaseTool] = {}
        self._init_tools()
        
        # 消息历史（ReAct 循环）
        self.message_history: List = []
    
    def _init_tools(self):
        """初始化工具集 - 将配置参数传递给工具"""
        self.tools = {
            "goto": GotoTool(
                timeout=self.page_timeout,
                wait_after=self.wait_after_navigate
            ),
            "input": InputTool(
                timeout=self.element_timeout,
                wait_after=self.wait_after_action,
                keyboard_delay=self.keyboard_delay,
                wait_after_search=self.wait_after_search
            ),
            "click": ClickTool(
                timeout=self.element_timeout,
                wait_after=self.wait_after_click
            ),
            "scroll": ScrollTool(
                distance=self.scroll_distance,
                wait_after=self.wait_after_scroll
            ),
            "wait": WaitTool(),
            "extract": ExtractTool(extract_text_length=self.extract_text_length),
            "done": DoneTool()
        }
    
    def _create_llm(self) -> ChatOpenAI:
        """创建或获取 LLM 实例"""
        if self._llm is None:
            self._llm = ChatOpenAI(
                model=self.model_name,
                api_key=self.api_key,
                base_url=self.base_url,
                temperature=0.1,
            )
        return self._llm
    
    def get_tool_schemas(self) -> List[Dict]:
        """获取所有工具的 Function Calling schema"""
        return [tool.to_function_schema() for tool in self.tools.values()]
    
    def _trim_history(self):
        """裁剪消息历史，防止上下文过长
        
        保留 SystemMessage + 最近的消息
        """
        if len(self.message_history) > self.max_history_messages:
            # 保留第一条 SystemMessage
            system_msg = self.message_history[0] if isinstance(self.message_history[0], SystemMessage) else None
            
            # 保留最近的消息
            recent_messages = self.message_history[-(self.max_history_messages - 1):]
            
            if system_msg:
                self.message_history = [system_msg] + recent_messages
            else:
                self.message_history = recent_messages
            
            logger.info(f"消息历史已裁剪至 {len(self.message_history)} 条")
    
    async def run(self, instruction: str, timeout_seconds: int = 300, allow_manual_login: bool = False) -> Dict[str, Any]:
        """执行任务
        
        Args:
            instruction: 用户指令
            timeout_seconds: 超时时间
            allow_manual_login: 是否允许手动登录（非 headless 模式下）
        """
        self.logs = []
        self.message_history = []  # 重置消息历史
        start_time = time.time()
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        
        try:
            self.logs.append(log_step(step=1, action="初始化", description=f"启动浏览器，模型: {self.model_name}"))
            await self._emit_log({"step": 1, "action": "初始化", "description": f"启动浏览器，模型: {self.model_name}"})
            
            # 确保状态目录存在
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            
            # 启动浏览器
            p = await async_playwright().start()
            browser = await p.chromium.launch(
                headless=self.headless,
                args=["--dns-over-https-mode=off", "--disable-async-dns"],
            )
            context = await browser.new_context()
            
            # 加载已保存的浏览器状态（cookies）
            state_file = STATE_DIR / "cookies.json"
            if state_file.exists():
                try:
                    cookies = json.loads(state_file.read_text())
                    await context.add_cookies(cookies)
                    self.logs.append(log_step(step=len(self.logs) + 1, action="加载状态", description="加载已保存的登录状态"))
                    await self._emit_log({"step": len(self.logs), "action": "加载状态", "description": "加载已保存的登录状态"})
                    logger.info("loaded_saved_cookies")
                except Exception as e:
                    logger.warning(f"加载状态失败: {str(e)}")
            
            page = await context.new_page()
            
            # 设置弹窗自动处理
            async def handle_dialog(dialog):
                logger.info(f"检测到弹窗: {dialog.message}")
                self.logs.append(log_step(step=len(self.logs) + 1, action="处理弹窗", description=f"自动关闭弹窗: {dialog.message[:50]}"))
                await dialog.dismiss()
            
            page.on("dialog", handle_dialog)
            
            result_data = {}
            done_event = asyncio.Event()  # 任务完成信号
            
            try:
                async with asyncio.timeout(timeout_seconds):
                    # ReAct 循环执行
                    result_data = await self._react_loop(page, instruction, usage, allow_manual_login=allow_manual_login)
                    
                    self.logs.append(log_step(step=len(self.logs) + 1, action="完成", description="任务执行完成"))
                    await self._emit_log({"step": len(self.logs), "action": "完成", "description": "任务执行完成", "done": True})
                    done_event.set()
                    
            except asyncio.TimeoutError:
                self.logs.append(log_step(step=len(self.logs) + 1, action="超时", description=f"任务超过 {timeout_seconds} 秒"))
                raise TimeoutError(f"任务执行超时（{timeout_seconds}秒）")
            
            finally:
                # 保存浏览器状态（cookies）
                try:
                    cookies = await context.cookies()
                    state_file = STATE_DIR / "cookies.json"
                    state_file.write_text(json.dumps(cookies, ensure_ascii=False, indent=2))
                    logger.info("saved_cookies")
                except Exception as e:
                    logger.warning(f"保存状态失败: {str(e)}")
                
                try:
                    await browser.close()
                except Exception as e:
                    logger.warning(f"浏览器关闭失败（可能已关闭）: {str(e)}")
                
                try:
                    await p.stop()
                except Exception as e:
                    logger.warning(f"Playwright 停止失败: {str(e)}")
            
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            return {
                "result": result_data,
                "logs": self.logs,
                "usage": usage,
                "execution_time_ms": execution_time_ms
            }
            
        except TimeoutError:
            raise
        except Exception as e:
            error_msg = str(e)
            logger.error(f"执行错误: {error_msg}")
            
            if "authentication" in error_msg.lower() or "api key" in error_msg.lower() or "401" in error_msg:
                raise InvalidAPIKeyError(f"API Key 无效: {error_msg}")
            else:
                raise ExecutionError(f"执行失败: {error_msg}")
    
    async def _react_loop(self, page, instruction: str, usage: Dict, allow_manual_login: bool = False) -> Dict[str, Any]:
        """ReAct 循环 - Thought → Action → Observation
        
        这是核心执行循环，采用主流的 ReAct 模式：
        1. Thought: AI 分析当前状态并思考下一步
        2. Action: 执行选定的工具
        3. Observation: 观察执行结果
        4. 循环直到任务完成或达到最大步数
        
        优化点：
        - 任务状态跟踪：记录已完成的关键步骤
        - 进度评估：让 AI 了解任务完成度
        - 智能错误恢复：根据错误类型提供建议
        """
        llm = self._create_llm()
        step_count = 0
        final_result = {}
        consecutive_errors = 0  # 连续错误计数
        max_consecutive_errors = 3  # 最大连续错误次数
        last_action = None  # 上一次执行的动作，用于检测重复
        repeat_count = 0  # 重复动作计数
        max_repeat = 2  # 相同动作最大重复次数
        
        # 任务状态跟踪
        task_state = {
            "completed_steps": [],  # 已完成的关键步骤
            "current_url": "",      # 当前 URL
            "last_page_title": "",  # 上次页面标题
            "extracted_data": {},   # 已提取的数据
            "nav_history": [],      # 导航历史
        }
        
        # 初始化消息历史 - 简洁的任务描述
        self.message_history = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=f"任务: {instruction}\n状态: 空白页\n动作: 根据任务选择合适工具开始执行。")
        ]
        
        while step_count < self.max_steps:
            step_count += 1
            logger.info(f"=== ReAct 步骤 {step_count}/{self.max_steps} ===")
            
            # 裁剪消息历史（防止过长）
            self._trim_history()
            
            # ========== 1. 获取当前页面状态 ==========
            page_state = await self._get_page_state(page)
            
            # 更新任务状态
            if page_state['url'] != task_state['current_url']:
                task_state['nav_history'].append(page_state['url'])
                task_state['current_url'] = page_state['url']
            task_state['last_page_title'] = page_state['title']
            
            # 检查并处理弹窗
            popup_handled = await self._handle_popups(page)
            if popup_handled:
                # 弹窗处理后重新获取页面状态
                await asyncio.sleep(0.5)
                page_state = await self._get_page_state(page)
            
            # 检查是否需要手动登录
            if not self.headless and allow_manual_login:
                await self._check_manual_login(page)
            
            # ========== 2. Thought - AI 思考下一步 ==========
            # 构建状态消息（包含任务进度）
            state_content = self._build_state_message(page_state, task_state, step_count)
            
            # 构建消息列表（历史 + 当前状态）
            # 注意：不把 state_content 加入历史，只在当前请求中使用
            messages = self.message_history.copy()
            
            # 如果有截图，使用多模态消息（保留文本信息）
            if page_state['screenshot']:
                messages.append(HumanMessage(content=[
                    {"type": "text", "text": state_content},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{page_state['screenshot']}"}}
                ]))
            else:
                messages.append(HumanMessage(content=state_content))
            
            try:
                # ========== 优先使用 Function Calling ==========
                if self.use_function_calling:
                    decision, action, params = await self._invoke_with_function_calling(
                        llm, messages, usage
                    )
                else:
                    decision, action, params = await self._invoke_with_json_parsing(
                        llm, messages, usage
                    )
                
                # 如果解析失败
                if not action and "raw_response" in decision:
                    consecutive_errors += 1
                    logger.warning(f"JSON解析失败 (连续 {consecutive_errors} 次): {decision['raw_response'][:200]}")
                    
                    if consecutive_errors >= max_consecutive_errors:
                        # 连续错误太多，尝试提取数据并结束
                        logger.error("连续错误次数过多，尝试提取数据并结束")
                        extract_tool = self.tools["extract"]
                        result = await extract_tool.execute(page)
                        return result.data if result.success else {}
                    
                    self.logs.append(log_step(
                        step=len(self.logs) + 1,
                        action="警告",
                        description="AI返回格式错误，重试..."
                    ))
                    # 添加观察结果到历史（紧凑格式）
                    self.message_history.append(AIMessage(content=decision.get("raw_response", "")[:100]))
                    self.message_history.append(HumanMessage(content="格式错误。返回: {\"action\":\"工具\", \"params\":{}}"))
                    continue
                
                # 重置连续错误计数
                consecutive_errors = 0
                
                # 检测重复动作（防止死循环）
                action_key = f"{action}:{json.dumps(params, sort_keys=True, ensure_ascii=False)}"
                if action_key == last_action:
                    repeat_count += 1
                    if repeat_count >= max_repeat:
                        logger.warning(f"检测到重复动作 {repeat_count} 次: {action_key}")
                        self.logs.append(log_step(
                            step=len(self.logs) + 1,
                            action="警告",
                            description=f"检测到重复动作，提示AI换一种方式"
                        ))
                        # 添加提示让 AI 换方式（紧凑格式）
                        self.message_history.append(HumanMessage(
                            content="重复操作!换方法:用其他选择器/滚动页面/等待加载"
                        ))
                        repeat_count = 0  # 重置计数
                        continue
                else:
                    repeat_count = 0
                last_action = action_key
                
                thought = decision.get("thought", decision.get("thinking", ""))
                
                # 记录思考过程
                log_entry = log_step(
                    step=len(self.logs) + 1,
                    action="思考",
                    description=thought[:100] if thought else f"执行 {action}"
                )
                self.logs.append(log_entry)
                await self._emit_log({
                    "step": log_entry.step,
                    "action": log_entry.action,
                    "description": log_entry.description,
                    "timestamp": log_entry.timestamp.isoformat() if hasattr(log_entry.timestamp, 'isoformat') else None
                })
                
                # 更新任务状态：记录即将执行的动作
                if action in ["goto", "click", "input"]:
                    task_state['completed_steps'].append(f"步骤{step_count}: {action}")
                
                # 添加 AI 思考到历史（紧凑格式）
                thought_summary = thought[:80] if thought else action
                self.message_history.append(AIMessage(content=f"{action}|{thought_summary}|{json.dumps(params, ensure_ascii=False)}"))
                
                # ========== 3. Action - 执行工具 ==========
                if action not in self.tools:
                    observation = f"错误：未知工具 '{action}'。可用工具: {list(self.tools.keys())}"
                    self.message_history.append(HumanMessage(content=f"Observation: {observation}"))
                    self.logs.append(log_step(step=len(self.logs) + 1, action="错误", description=observation))
                    continue
                
                tool = self.tools[action]
                tool_result = await tool.execute(page, **params)
                
                # 记录执行结果
                log_entry = log_step(
                    step=len(self.logs) + 1,
                    action=f"执行 {action}",
                    description=tool_result.output[:100] if tool_result.output else tool_result.error[:100]
                )
                self.logs.append(log_entry)
                await self._emit_log({
                    "step": log_entry.step,
                    "action": log_entry.action,
                    "description": log_entry.description,
                    "timestamp": log_entry.timestamp.isoformat() if hasattr(log_entry.timestamp, 'isoformat') else None
                })
                
                # ========== 4. Observation - 观察结果 ==========
                if tool_result.success:
                    observation = f"执行成功: {tool_result.output}"
                    consecutive_errors = 0  # 成功时重置错误计数
                else:
                    observation = f"执行失败: {tool_result.error}"
                    consecutive_errors += 1
                    
                    # 检查是否需要提前终止
                    if consecutive_errors >= max_consecutive_errors:
                        logger.error(f"连续错误 {consecutive_errors} 次，尝试提取数据并结束")
                        self.logs.append(log_step(step=len(self.logs) + 1, action="错误", description=f"连续失败 {consecutive_errors} 次，强制结束"))
                        extract_tool = self.tools["extract"]
                        result = await extract_tool.execute(page)
                        if result.success:
                            final_result = result.data
                        return final_result
                
                # 检查是否任务完成
                if action == "done" or tool_result.data.get("done"):
                    final_result = tool_result.data.get("result", {})
                    # 发送完成日志
                    await self._emit_log({
                        "step": len(self.logs) + 1,
                        "action": "完成",
                        "description": tool_result.data.get("summary", "任务完成"),
                        "done": True,
                        "result": final_result
                    })
                    break  # 任务完成，不添加额外消息
                
                # 如果是 extract，保存结果但继续执行
                if action == "extract":
                    final_result = tool_result.data
                
                # 添加观察结果到历史（包含关键执行信息）
                obs_summary = observation[:100]
                
                # 如果执行成功且有意义的数据，保存关键信息
                if tool_result.success and tool_result.data:
                    key_info = ""
                    if "url" in tool_result.data:
                        key_info += f"URL: {tool_result.data['url'][:60]} "
                    if "title" in tool_result.data:
                        key_info += f"标题: {tool_result.data['title'][:30]}"
                    self.message_history.append(HumanMessage(content=f"✓ {action}: {key_info or obs_summary}"))
                else:
                    status = "✓" if tool_result.success else "✗"
                    self.message_history.append(HumanMessage(content=f"{status} {action}: {obs_summary}"))
                
            except Exception as e:
                consecutive_errors += 1
                logger.warning(f"ReAct 循环错误 (连续 {consecutive_errors} 次): {str(e)}")
                self.message_history.append(HumanMessage(content=f"Observation: 执行出错 - {str(e)}"))
                self.logs.append(log_step(step=len(self.logs) + 1, action="错误", description=f"执行异常: {str(e)[:50]}"))
                
                if consecutive_errors >= max_consecutive_errors:
                    logger.error("连续错误次数过多，尝试提取数据并结束")
                    extract_tool = self.tools["extract"]
                    result = await extract_tool.execute(page)
                    return result.data if result.success else {}
                continue
        
        # 达到最大步数
        if step_count >= self.max_steps:
            logger.warning(f"达到最大步数 {self.max_steps}")
            self.logs.append(log_step(step=len(self.logs) + 1, action="警告", description=f"达到最大步数 {self.max_steps}，强制结束"))
            # 尝试提取数据
            extract_tool = self.tools["extract"]
            result = await extract_tool.execute(page)
            if result.success:
                final_result = result.data
        
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        return final_result
    
    async def _emit_log(self, log_data: Dict):
        """发送日志到回调函数（用于实时推送）"""
        if self.log_callback:
            try:
                await self.log_callback(log_data)
            except Exception as e:
                logger.warning(f"日志回调失败: {str(e)}")
    
    async def _invoke_with_function_calling(self, llm, messages: List, usage: Dict) -> tuple:
        """使用 OpenAI Function Calling 调用 LLM
        
        Returns:
            tuple: (decision_dict, action, params)
        """
        try:
            # 绑定工具
            llm_with_tools = llm.bind_tools(self.get_tool_schemas())
            
            response = await llm_with_tools.ainvoke(messages)
            usage["prompt_tokens"] += response.usage_metadata.get("input_tokens", 0)
            usage["completion_tokens"] += response.usage_metadata.get("output_tokens", 0)
            
            # 检查是否有工具调用
            if response.tool_calls:
                tool_call = response.tool_calls[0]
                action = tool_call["name"]
                params = tool_call["args"]
                
                # 参数后处理：确保必填参数存在
                if action == "input" and "press_enter" not in params:
                    params["press_enter"] = False
                
                decision = {
                    "thought": f"使用 {action} 工具",
                    "action": action,
                    "params": params
                }
                logger.info(f"Function Calling: {action}({params})")
                return decision, action, params
            
            # 没有工具调用，尝试解析文本
            logger.info(f"AI返回: {response.content[:300]}")
            
            # 尝试解析紧凑格式: action|thought|params_json
            decision = self._parse_compact_format(response.content)
            if not decision:
                decision = self._parse_json(response.content)
            
            action = decision.get("action", "")
            params = decision.get("params", {})
            
            # 如果解析到有效的 action，记录成功
            if action:
                logger.info(f"解析成功: action={action}, params={params}")
            
            return decision, action, params
            
        except Exception as e:
            logger.warning(f"Function Calling 失败: {str(e)}，降级到 JSON 解析")
            # 降级到普通 JSON 解析
            return await self._invoke_with_json_parsing(llm, messages, usage)
    
    async def _invoke_with_json_parsing(self, llm, messages: List, usage: Dict) -> tuple:
        """使用普通 JSON 解析调用 LLM
        
        Returns:
            tuple: (decision_dict, action, params)
        """
        response = await llm.ainvoke(messages)
        usage["prompt_tokens"] += response.usage_metadata.get("input_tokens", 0)
        usage["completion_tokens"] += response.usage_metadata.get("output_tokens", 0)
        
        logger.info(f"AI返回: {response.content[:300]}")
        
        # 尝试解析紧凑格式: action|thought|params_json
        decision = self._parse_compact_format(response.content)
        if not decision:
            decision = self._parse_json(response.content)
        
        action = decision.get("action", "")
        params = decision.get("params", {})
        
        # 如果解析到有效的 action，记录成功
        if action:
            logger.info(f"解析成功: action={action}, params={params}")
        
        return decision, action, params
    
    def _build_state_message(self, page_state: Dict, task_state: Dict = None, step_count: int = 0) -> str:
        """构建紧凑的页面状态消息（减少token）
        """
        # 紧凑格式：仅保留关键信息
        url = page_state['url'][:80] if len(page_state['url']) > 80 else page_state['url']
        title = page_state['title'][:50] if len(page_state['title']) > 50 else page_state['title']
        snippet = page_state['snippet'][:200] if page_state['snippet'] else "空白"
        
        # 元素列表简化：只保留关键字段
        elements_str = ""
        if page_state['elements']:
            for el in page_state['elements'][:10]:  # 只显示前10个
                selector = el.get('suggestedSelector') or f"nth({el['idx']})"
                text = el.get('text', '')[:20]
                elements_str += f"[{el['idx']}] {el['tag']}/{el.get('type','')} {text} → {selector}\n"
        
        # 进度信息简化
        progress = ""
        if task_state and task_state['nav_history']:
            progress = f"导航: {'→'.join(task_state['nav_history'][-2:])}\n"
        
        return f"""状态({step_count}/{self.max_steps}): {url}
标题: {title}
摘要: {snippet[:150]}
元素:
{elements_str if elements_str else '无'}
{progress}决策: 返回 {{\"thought\":\"...\", \"action\":\"工具\", \"params\":{{}}}}"""
    
    def _get_context_hint(self, action: str, params: Dict, result: ToolResult, task_state: Dict) -> str:
        """根据执行结果提供上下文提示
        
        帮助 AI 更好地理解当前状态和下一步建议
        """
        hints = []
        
        if action == "goto":
            hints.append("页面已加载，建议检查页面元素，确认是否需要进一步操作。")
        
        elif action == "input":
            if params.get("press_enter"):
                hints.append("输入已提交，页面可能正在加载或已跳转，建议等待后检查结果。")
            else:
                hints.append("输入完成，如需提交请使用 click 点击提交按钮，或使用 input 的 press_enter 参数。")
        
        elif action == "click":
            if result.data.get("navigated"):
                hints.append(f"页面已跳转到: {result.data.get('new_url', '新页面')}，建议检查是否到达目标页面。")
            else:
                hints.append("点击成功，请观察页面变化，确认是否达到预期效果。")
        
        elif action == "scroll":
            hints.append("页面已滚动，可能有新的元素出现，建议查看更新后的元素列表。")
        
        elif action == "extract":
            hints.append("数据已提取，如果信息足够，可以使用 done 工具完成任务。")
        
        return "\n".join(hints) if hints else ""
    
    async def _get_page_state(self, page) -> Dict[str, Any]:
        """获取当前页面状态"""
        try:
            url = page.url
            title = await page.title()
            snippet = await page.evaluate("() => document.body.innerText.substring(0, 500)") if url != "about:blank" else ""
            elements = await self._get_interactive_elements(page)
            screenshot = ""
            
            if url != "about:blank" and url.startswith("http"):
                screenshot = await self._take_screenshot(page)
            
            return {
                "url": url,
                "title": title,
                "snippet": snippet or "空白页",
                "elements": elements,
                "screenshot": screenshot
            }
        except Exception as e:
            logger.warning(f"获取页面状态失败: {str(e)}")
            return {
                "url": "about:blank",
                "title": "",
                "snippet": "",
                "elements": [],
                "screenshot": ""
            }
    
    async def _handle_popups(self, page) -> bool:
        """处理页面弹窗/遮罩层
        
        Returns:
            bool: 是否处理了弹窗
        """
        try:
            has_popup = await page.evaluate("""
                () => {
                    const modals = document.querySelectorAll('[class*="modal"], [class*="popup"], [class*="dialog"], [class*="overlay"], [class*="toast"], [class*="notice"]');
                    for (const m of modals) {
                        const rect = m.getBoundingClientRect();
                        const style = window.getComputedStyle(m);
                        if (rect.width > 0 && rect.height > 0 && 
                            style.display !== 'none' && style.visibility !== 'hidden' &&
                            style.zIndex > 100) {
                            return true;
                        }
                    }
                    return false;
                }
            """)
            
            if has_popup:
                logger.info("检测到弹窗，尝试关闭...")
                close_selectors = [
                    "[class*='close']:visible",
                    "[class*='Close']:visible", 
                    "[aria-label*='关闭']:visible",
                    "[aria-label*='close']:visible",
                    "[title*='关闭']:visible",
                    "[title*='close']:visible",
                    "button[class*='close']:visible",
                    ".modal-close:visible",
                    ".dialog-close:visible",
                ]
                
                for selector in close_selectors:
                    try:
                        close_btn = page.locator(selector).first
                        if await close_btn.is_visible(timeout=500):
                            await close_btn.click(timeout=1000)
                            logger.info(f"点击关闭按钮: {selector}")
                            self.logs.append(log_step(step=len(self.logs) + 1, action="关闭弹窗", description="点击关闭按钮"))
                            await asyncio.sleep(0.5)
                            return True
                    except Exception as e:
                        logger.debug(f"尝试选择器 {selector} 失败: {str(e)}")
                        continue
                
                # 按 ESC 关闭
                await page.keyboard.press("Escape")
                await asyncio.sleep(0.5)
                return True
                
        except Exception as e:
            logger.warning(f"弹窗处理失败: {str(e)}")
        
        return False
    
    async def _check_manual_login(self, page):
        """检查是否需要手动登录"""
        try:
            page_text = await page.evaluate("() => document.body.innerText") if page.url != "about:blank" else ""
            if any(keyword in page_text for keyword in ["验证码", "请完成安全验证", "人机验证", "滑动验证", "安全校验"]):
                self.logs.append(log_step(step=len(self.logs) + 1, action="等待登录", description="检测到验证码，请在浏览器中手动处理（60秒）..."))
                logger.info("detected_captcha")
                await asyncio.sleep(self.manual_login_timeout)
        except Exception as e:
            logger.warning(f"检查验证码失败: {str(e)}")
    
    async def _get_interactive_elements(self, page) -> List[Dict]:
        """获取页面可交互元素
        
        返回格式优化，包含更多有用的定位信息
        """
        try:
            js_code = """
                () => {
                    const results = [];
                    const maxElements = %d;
                    
                    // 按重要性排序的元素选择器
                    const importantSelectors = [
                        'input[type="text"]:visible',
                        'input[type="search"]:visible', 
                        'input:not([type]):visible',
                        'textarea:visible',
                        'button:visible',
                        'a:visible',
                        '[role="button"]:visible',
                        'select:visible'
                    ];
                    
                    const seen = new Set();
                    
                    for (const selector of importantSelectors) {
                        const elements = document.querySelectorAll(selector.replace(':visible', ''));
                        for (const el of elements) {
                            if (results.length >= maxElements) break;
                            
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            
                            // 过滤不可见元素
                            if (rect.width <= 0 || rect.height <= 0 || 
                                style.display === 'none' || 
                                style.visibility === 'hidden' || 
                                el.disabled ||
                                rect.top < 0) continue;
                            
                            // 去重
                            const key = el.outerHTML.substring(0, 100);
                            if (seen.has(key)) continue;
                            seen.add(key);
                            
                            const tag = el.tagName.toLowerCase();
                            const type = el.type || '';
                            const text = (el.innerText || el.value || el.placeholder || '').substring(0, 30).trim();
                            const placeholder = (el.placeholder || '').substring(0, 30);
                            const name = el.name || '';
                            const id = el.id || '';
                            const ariaLabel = el.getAttribute('aria-label') || '';
                            
                            // 构建推荐的选择器
                            let suggestedSelector = '';
                            if (id) {
                                suggestedSelector = '#' + id;
                            } else if (name) {
                                suggestedSelector = tag + '[name="' + name + '"]';
                            } else if (placeholder) {
                                suggestedSelector = tag + '[placeholder*="' + placeholder.substring(0, 15) + '"]';
                            } else if (text && text.length > 0 && text.length < 20) {
                                suggestedSelector = 'text: ' + text;
                            }
                            
                            results.push({
                                idx: results.length,
                                tag: tag,
                                type: type,
                                text: text || placeholder || ariaLabel,
                                name: name,
                                id: id,
                                placeholder: placeholder,
                                suggestedSelector: suggestedSelector
                            });
                        }
                    }
                    return results;
                }
            """ % self.max_elements
            
            return await page.evaluate(js_code) or []
        except Exception as e:
            logger.warning(f"获取元素失败: {str(e)}")
            return []
    
    async def _take_screenshot(self, page) -> str:
        """截取页面截图并返回 base64 编码"""
        try:
            screenshot_bytes = await page.screenshot(type="png", full_page=False)
            return base64.b64encode(screenshot_bytes).decode("utf-8")
        except Exception as e:
            logger.warning(f"截图失败: {str(e)}")
            return ""
    
    def _parse_json(self, text: str) -> Dict:
        """解析 JSON - 支持多种格式"""
        # 1. 直接解析
        try:
            return json.loads(text)
        except:
            pass
        
        # 2. 移除 markdown 代码块标记
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
            cleaned = re.sub(r'\s*```$', '', cleaned)
            try:
                return json.loads(cleaned)
            except:
                pass
        
        # 3. 提取第一个完整的 JSON 对象
        brace_count = 0
        start_idx = -1
        for i, char in enumerate(text):
            if char == '{':
                if start_idx == -1:
                    start_idx = i
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and start_idx >= 0:
                    try:
                        return json.loads(text[start_idx:i+1])
                    except json.JSONDecodeError as e:
                        logger.debug(f"JSON 解析失败 (位置 {start_idx}-{i}): {str(e)}")
                        start_idx = -1  # 重置，继续查找下一个 JSON 对象
        
        # 4. 尝试正则提取
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as e:
                logger.debug(f"正则提取的 JSON 解析失败: {str(e)}")
        
        logger.warning(f"无法解析为 JSON，原始响应: {text[:200]}")
        return {"raw_response": text}
    
    def _parse_compact_format(self, text: str) -> Dict:
        """解析紧凑格式: action|thought|params_json
        
        示例: done|任务完成|{"result":{}, "summary":"完成"}
        
        注意: thought 中可能包含 | 字符，所以需要从后往前解析
        """
        # 检查是否是紧凑格式（至少有一个竖线分隔）
        if '|' not in text:
            return None
        
        parts = text.split('|')
        if len(parts) < 2:
            return None
        
        action = parts[0].strip()
        
        # 验证 action 是否是有效工具
        valid_actions = list(self.tools.keys())
        if action not in valid_actions:
            return None
        
        # 解析 params（从后往前找 JSON 对象）
        params = {}
        thought_parts = []
        
        # 从最后一个部分开始，尝试解析 JSON
        for i in range(len(parts) - 1, 0, -1):
            candidate = parts[i].strip()
            
            # 尝试解析为 JSON
            if candidate.startswith('{'):
                try:
                    params = json.loads(candidate)
                    # JSON 解析成功，前面的部分都是 thought
                    thought_parts = parts[1:i]
                    break
                except json.JSONDecodeError:
                    # 不是有效 JSON，加入 thought
                    thought_parts.insert(0, candidate)
            else:
                # 不是 JSON 开头，加入 thought
                thought_parts.insert(0, candidate)
        
        # 如果没有找到 JSON，所有中间部分都是 thought
        if not thought_parts and len(parts) >= 2:
            thought_parts = parts[1:]
        
        # 如果仍然没有 params，尝试在整个文本中找 JSON
        if not params:
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
            if json_match:
                try:
                    params = json.loads(json_match.group(0))
                except:
                    params = {}
        
        thought = '|'.join(thought_parts).strip() if thought_parts else ""
        
        logger.info(f"紧凑格式解析成功: action={action}, thought={thought[:50]}")
        
        return {
            "thought": thought,
            "action": action,
            "params": params
        }
