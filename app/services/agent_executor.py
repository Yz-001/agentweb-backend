"""
Agent 执行服务 - 使用 LangChain + Playwright 实现
完全由 AI 推理，循环思考-执行模式
支持浏览器状态持久化，避免触发验证码
"""
import asyncio
import json
import re
import time
import sys
import pathlib
from typing import Dict, Any, List, Optional

# 设置 UTF-8 编码
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

from langchain_openai import ChatOpenAI
from patchright.async_api import async_playwright

from app.models.run import LogEntry
from app.core.exceptions import InvalidAPIKeyError, ExecutionError, TimeoutError
from app.utils.logger import logger, log_step

# 浏览器状态文件目录
STATE_DIR = pathlib.Path("data/browser_state")


class AgentExecutor:
    """Agent 执行器 - 完全由 AI 推理"""
    
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
        element_text_length: int = 30
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
    
    def _create_llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                model=self.model_name,
                api_key=self.api_key,
                base_url=self.base_url,
                temperature=0.1,
            )
        return self._llm
    
    async def run(self, instruction: str, timeout_seconds: int = 300, allow_manual_login: bool = False) -> Dict[str, Any]:
        """执行任务
        
        Args:
            instruction: 用户指令
            timeout_seconds: 超时时间
            allow_manual_login: 是否允许手动登录（非 headless 模式下）
        """
        self.logs = []
        start_time = time.time()
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        
        try:
            self.logs.append(log_step(step=1, action="初始化", description=f"启动浏览器，模型: {self.model_name}"))
            
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
                    logger.info("loaded_saved_cookies")
                except Exception as e:
                    logger.warning(f"加载状态失败: {str(e)}")
            
            page = await context.new_page()
            
            result_data = {}
            
            try:
                async with asyncio.timeout(timeout_seconds):
                    # 循环思考-执行
                    result_data = await self._think_and_act(page, instruction, usage, allow_manual_login=allow_manual_login)
                    
                    self.logs.append(log_step(step=len(self.logs) + 1, action="完成", description="任务执行完成"))
                    
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
                
                await browser.close()
                await p.stop()
            
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
    
    async def _think_and_act(self, page, instruction: str, usage: Dict, step_count: int = 0, allow_manual_login: bool = False) -> Dict[str, Any]:
        """思考并执行 - 循环调用直到任务完成"""
        if step_count >= self.max_steps:
            logger.warning(f"达到最大步数 {self.max_steps}，强制结束")
            return await self._extract_data(page, instruction, usage)
        
        llm = self._create_llm()
        
        # 获取当前页面状态
        page_url = page.url
        page_title = await page.title()
        elements = await self._get_interactive_elements(page)
        
        # 检查是否需要手动登录（非 headless 且首次访问某些网站）
        if not self.headless and allow_manual_login and page_url != "about:blank":
            # 检查是否有验证码或登录页面特征
            page_text = await page.evaluate("() => document.body.innerText")
            if any(keyword in page_text for keyword in ["验证码", "登录", "请输入验证码", "人机验证"]):
                self.logs.append(log_step(step=len(self.logs) + 1, action="等待登录", description="检测到登录/验证码页面，请在浏览器中手动处理..."))
                logger.info("detected_login_page")
                # 等待用户处理
                await asyncio.sleep(self.manual_login_timeout)
        
        page_snippet = await page.evaluate("() => document.body.innerText.substring(0, 500)")
        
        # 构建思考 prompt
        prompt = f"""你是一个网页自动化 Agent。请观察当前页面状态，思考下一步该做什么。

用户任务: {instruction}

当前页面状态:
- URL: {page_url}
- 标题: {page_title}
- 页面摘要: {page_snippet[:300]}

可交互元素 (共 {len(elements)} 个):
{json.dumps(elements, ensure_ascii=False, indent=2)}

请思考并返回 JSON:

{{
    "thinking": "当前页面是什么？用户任务完成了吗？下一步应该做什么？",
    "action": "操作类型",
    "params": {{}},
    "description": "操作描述"
}}

支持的 action:
1. "goto" - 导航到 URL: {{"url": "https://..."}}
2. "input" - 输入文本: {{"selector": "nth(索引) 或 CSS选择器", "value": "输入内容"}}
3. "search" - 在输入框输入并搜索（自动按回车）: {{"selector": "nth(索引)", "value": "搜索内容"}}
4. "click" - 点击元素: {{"selector": "nth(索引) 或 CSS选择器"}}
5. "scroll" - 滚动页面: {{}}
6. "wait" - 等待: {{"seconds": 2}}
7. "extract" - 提取数据并结束: {{"fields": ["字段1", "字段2"]}}
8. "done" - 任务已完成，返回结果: {{"result": {{}}}}

重要提示:
- 如果页面 URL 是 about:blank，需要先 goto
- 如果需要在搜索框输入并搜索，使用 search 操作（会自动按回车）
- 如果使用 input 操作，之后需要 click 搜索按钮或再执行 click 操作
- 如果已经在结果页面，可以 extract 提取数据
- 元素索引范围: 0 到 {len(elements) - 1}

只返回 JSON，不要其他内容。"""

        try:
            response = await llm.ainvoke(prompt)
            usage["prompt_tokens"] += response.usage_metadata.get("input_tokens", 0)
            usage["completion_tokens"] += response.usage_metadata.get("output_tokens", 0)
            
            decision = self._parse_json(response.content)
            
            thinking = decision.get("thinking", "")
            action = decision.get("action", "")
            params = decision.get("params", {})
            description = decision.get("description", "")
            
            # 记录思考过程
            self.logs.append(log_step(
                step=len(self.logs) + 1, 
                action="思考", 
                description=thinking[:100]
            ))
            
            # 执行动作
            should_continue = True
            result = {}
            
            if action == "goto":
                url = params.get("url", "")
                if url:
                    self.logs.append(log_step(step=len(self.logs) + 1, action="导航", description=f"打开 {url}"))
                    await page.goto(url, timeout=self.page_timeout, wait_until="domcontentloaded")
                    await asyncio.sleep(self.wait_after_navigate)
            
            elif action == "input":
                selector = params.get("selector", "")
                value = params.get("value", "")
                if selector and value:
                    self.logs.append(log_step(step=len(self.logs) + 1, action="输入", description=f"输入: {value[:30]}"))
                    await self._do_input(page, selector, value)
            
            elif action == "search":
                selector = params.get("selector", "")
                value = params.get("value", "")
                if selector and value:
                    self.logs.append(log_step(step=len(self.logs) + 1, action="搜索", description=f"输入并搜索: {value[:30]}"))
                    await self._do_input(page, selector, value)
                    await asyncio.sleep(self.wait_after_action)
                    await page.keyboard.press("Enter")
                    await asyncio.sleep(self.wait_after_search)
            
            elif action == "click":
                selector = params.get("selector", "")
                if selector:
                    self.logs.append(log_step(step=len(self.logs) + 1, action="点击", description=description))
                    await self._do_click(page, selector)
                    await asyncio.sleep(self.wait_after_navigate)
            
            elif action == "scroll":
                self.logs.append(log_step(step=len(self.logs) + 1, action="滚动", description="向下滚动页面"))
                await page.evaluate(f"window.scrollBy(0, {self.scroll_distance})")
                await asyncio.sleep(self.wait_after_scroll)
            
            elif action == "wait":
                seconds = params.get("seconds", 2)
                self.logs.append(log_step(step=len(self.logs) + 1, action="等待", description=f"等待 {seconds} 秒"))
                await asyncio.sleep(seconds)
            
            elif action == "extract":
                fields = params.get("fields", [])
                self.logs.append(log_step(step=len(self.logs) + 1, action="提取", description="提取页面数据"))
                result = await self._extract_data(page, instruction, usage, fields)
                should_continue = False
            
            elif action == "done":
                result = params.get("result", {})
                should_continue = False
            
            else:
                # 未知操作，尝试提取数据
                result = await self._extract_data(page, instruction, usage)
                should_continue = False
            
            # 如果需要继续，递归调用
            if should_continue:
                result = await self._think_and_act(page, instruction, usage, step_count + 1, allow_manual_login)
            
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
            return result
            
        except Exception as e:
            logger.warning(f"AI 思考失败: {str(e)}")
            # 降级：直接提取数据
            return await self._extract_data(page, instruction, usage)
    
    async def _do_input(self, page, selector: str, value: str):
        """执行输入操作"""
        try:
            if selector.startswith("nth("):
                idx = int(selector.replace("nth(", "").replace(")", ""))
                elements = await self._get_interactive_elements(page)
                if idx < len(elements):
                    el = elements[idx]
                    # 尝试多种方式定位
                    if el.get('id'):
                        await page.locator(f"#{el['id']}").fill(value, timeout=self.element_timeout)
                    elif el.get('name'):
                        await page.locator(f"[name='{el['name']}']").fill(value, timeout=self.element_timeout)
                    else:
                        await page.locator("input:visible").nth(idx).fill(value, timeout=self.element_timeout)
                else:
                    await page.locator("input:visible").first.fill(value, timeout=self.element_timeout)
            else:
                await page.locator(selector).first.fill(value, timeout=self.element_timeout)
            
            await asyncio.sleep(self.wait_after_action)
            
        except Exception as e:
            logger.warning(f"输入失败: {str(e)}")
            # 降级：键盘输入
            await page.keyboard.type(value, delay=self.keyboard_delay)
    
    async def _do_click(self, page, selector: str):
        """执行点击操作"""
        try:
            if selector.startswith("nth("):
                idx = int(selector.replace("nth(", "").replace(")", ""))
                elements = await self._get_interactive_elements(page)
                if idx < len(elements):
                    el = elements[idx]
                    if el.get('id'):
                        await page.locator(f"#{el['id']}").click()
                    elif el.get('tag') == 'a' or el.get('tag') == 'button':
                        await page.locator(f"{el['tag']}:visible").nth(idx).click()
                    else:
                        await page.keyboard.press("Enter")
                else:
                    await page.keyboard.press("Enter")
            else:
                await page.locator(selector).first.click()
            
            await asyncio.sleep(self.wait_after_click)
            
        except Exception as e:
            logger.warning(f"点击失败: {str(e)}")
            await page.keyboard.press("Enter")
    
    async def _get_interactive_elements(self, page) -> List[Dict]:
        """获取页面可交互元素"""
        try:
            js_code = """
                () => {
                    const results = [];
                    document.querySelectorAll('input:not([type="hidden"]), button, a, textarea, select, [role="button"], [onclick]').forEach((el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        
                        if (rect.width > 0 && 
                            rect.height > 0 && 
                            rect.top >= 0 &&
                            style.display !== 'none' &&
                            style.visibility !== 'hidden' &&
                            !el.disabled) {
                            
                            const tag = el.tagName.toLowerCase();
                            const type = el.type || '';
                            const text = (el.innerText || el.value || el.placeholder || el.name || el.id || '').substring(0, %d).trim();
                            const placeholder = (el.placeholder || '').substring(0, %d);
                            
                            results.push({
                                tag: tag,
                                type: type,
                                text: text,
                                placeholder: placeholder,
                                name: el.name || '',
                                id: el.id || ''
                            });
                        }
                    });
                    
                    // 排序：输入框优先
                    results.sort((a, b) => {
                        const aIsInput = ['input', 'textarea'].includes(a.tag);
                        const bIsInput = ['input', 'textarea'].includes(b.tag);
                        if (aIsInput && !bIsInput) return -1;
                        if (!aIsInput && bIsInput) return 1;
                        return 0;
                    });
                    
                    return results;
                }
            """ % (self.element_text_length, self.element_text_length)
            
            elements = await page.evaluate(js_code)
            
            if elements:
                elements = elements[:self.max_elements]
                for i, el in enumerate(elements):
                    el['idx'] = i
            
            return elements or []
        except Exception as e:
            logger.warning(f"获取元素失败: {str(e)}")
            return []
    
    async def _extract_data(self, page, instruction: str, usage: Dict, fields: List[str] = None) -> Dict[str, Any]:
        """提取数据"""
        llm = self._create_llm()
        
        try:
            page_text = await page.evaluate("() => document.body.innerText")
            page_url = page.url
            page_title = await page.title()
            
            fields_desc = f"提取字段: {', '.join(fields)}" if fields else "提取相关数据"
            
            prompt = f"""从当前页面提取数据。

页面 URL: {page_url}
页面标题: {page_title}
页面内容（前{self.extract_text_length}字符）:
{page_text[:self.extract_text_length]}

用户任务: {instruction}
{fields_desc}

返回 JSON 格式数据。找不到的字段设为 null。只返回 JSON。"""

            response = await llm.ainvoke(prompt)
            usage["prompt_tokens"] += response.usage_metadata.get("input_tokens", 0)
            usage["completion_tokens"] += response.usage_metadata.get("output_tokens", 0)
            
            return self._parse_json(response.content)
            
        except Exception as e:
            logger.warning(f"提取数据失败: {str(e)}")
            return {
                "url": page.url,
                "title": await page.title(),
                "snippet": (await page.evaluate("() => document.body.innerText"))[:self.snippet_length]
            }
    
    def _parse_json(self, text: str) -> Dict:
        """解析 JSON"""
        try:
            return json.loads(text)
        except:
            pass
        
        # 尝试提取 JSON
        match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except:
                pass
        
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except:
                pass
        
        return {"raw_response": text}