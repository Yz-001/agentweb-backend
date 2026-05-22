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
from langchain_core.messages import HumanMessage
from patchright.async_api import async_playwright
import base64

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
            
            # 设置弹窗自动处理
            async def handle_dialog(dialog):
                logger.info(f"检测到弹窗: {dialog.message}")
                self.logs.append(log_step(step=len(self.logs) + 1, action="处理弹窗", description=f"自动关闭弹窗: {dialog.message[:50]}"))
                await dialog.dismiss()
            
            page.on("dialog", handle_dialog)
            
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
        
        # 检查并处理页面弹窗/遮罩层（通过视觉识别）
        try:
            # 先检查是否有明显的弹窗元素
            has_popup = await page.evaluate("""
                () => {
                    // 检查常见的弹窗特征
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
                # 尝试多种方式关闭弹窗
                closed = False
                
                # 1. 尝试点击关闭按钮（X 图标）
                close_selectors = [
                    "[class*='close']:visible",
                    "[class*='Close']:visible", 
                    "[aria-label*='关闭']:visible",
                    "[aria-label*='close']:visible",
                    "[title*='关闭']:visible",
                    "[title*='close']:visible",
                    "button[class*='close']:visible",
                    "span[class*='close']:visible",
                    "i[class*='close']:visible",
                    ".modal-close:visible",
                    ".dialog-close:visible",
                    ".popup-close:visible",
                ]
                
                for selector in close_selectors:
                    try:
                        close_btn = page.locator(selector).first
                        if await close_btn.is_visible(timeout=500):
                            await close_btn.click(timeout=1000)
                            logger.info(f"点击关闭按钮: {selector}")
                            self.logs.append(log_step(step=len(self.logs) + 1, action="关闭弹窗", description=f"点击关闭按钮"))
                            closed = True
                            await asyncio.sleep(0.5)
                            break
                    except:
                        continue
                
                # 2. 如果没找到关闭按钮，尝试按 ESC
                if not closed:
                    await page.keyboard.press("Escape")
                    logger.info("按 ESC 尝试关闭弹窗")
                    await asyncio.sleep(0.5)
                    
        except Exception as e:
            logger.warning(f"弹窗处理失败: {str(e)}")
        
        # 检查是否需要手动登录（非 headless 模式下）
        if not self.headless and allow_manual_login:
            # 检查是否有验证码或登录页面特征
            try:
                page_text = await page.evaluate("() => document.body.innerText") if page_url != "about:blank" else ""
                if any(keyword in page_text for keyword in ["验证码", "请完成安全验证", "人机验证", "滑动验证", "安全校验"]):
                    self.logs.append(log_step(step=len(self.logs) + 1, action="等待登录", description="检测到验证码，请在浏览器中手动处理（60秒）..."))
                    logger.info("detected_captcha")
                    # 等待用户处理
                    await asyncio.sleep(self.manual_login_timeout)
                    # 重新检查是否还有验证码
                    page_text = await page.evaluate("() => document.body.innerText")
                    if any(keyword in page_text for keyword in ["验证码", "请完成安全验证", "人机验证"]):
                        self.logs.append(log_step(step=len(self.logs) + 1, action="警告", description="验证码可能未处理完成，继续执行..."))
            except Exception as e:
                logger.warning(f"检查验证码失败: {str(e)}")
        
        page_snippet = await page.evaluate("() => document.body.innerText.substring(0, 500)")
        
        # 截取页面截图（空白页不截图）
        screenshot_base64 = ""
        if page_url != "about:blank" and page_url.startswith("http"):
            screenshot_base64 = await self._take_screenshot(page)
        
        # 构建思考 prompt
        text_content = f"""用户任务: {instruction}

当前页面状态:
- URL: {page_url}
- 标题: {page_title}
- 页面摘要: {page_snippet[:300] if page_snippet else '空白页'}

可交互元素 (共 {len(elements)} 个):
{json.dumps(elements, ensure_ascii=False, indent=2) if elements else '无'}

请观察截图，分析当前页面状态，返回下一步操作的 JSON。

【必须】返回格式（仅 JSON，不要其他文字）:
{{"thinking": "思考内容", "action": "操作", "params": {{}}, "description": "描述"}}

action 可选值:
- goto: {{"action": "goto", "params": {{"url": "https://..."}}}}
- search: {{"action": "search", "params": {{"selector": "nth(0)", "value": "搜索内容"}}}}
- click: {{"action": "click", "params": {{"text": "链接文本"}}}}
- extract: {{"action": "extract", "params": {{}}}}
- done: {{"action": "done", "params": {{"result": {{}}}}}}

当前应该做什么？返回 JSON："""

        try:
            # 根据是否有截图选择消息类型
            if screenshot_base64:
                # 使用多模态消息（图片+文本）
                message = HumanMessage(content=[
                    {"type": "text", "text": text_content},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_base64}"}}
                ])
            else:
                # 纯文本消息
                message = HumanMessage(content=text_content)
            
            response = await llm.ainvoke([message])
            usage["prompt_tokens"] += response.usage_metadata.get("input_tokens", 0)
            usage["completion_tokens"] += response.usage_metadata.get("output_tokens", 0)
            
            decision = self._parse_json(response.content)
            
            # 记录 AI 原始返回（调试用）
            logger.info(f"AI返回: {response.content[:200]}")
            
            thinking = decision.get("thinking", "")
            action = decision.get("action", "")
            params = decision.get("params", {})
            description = decision.get("description", "")
            
            # 如果解析失败，记录原始响应
            if not action and "raw_response" in decision:
                logger.warning(f"JSON解析失败，原始响应: {decision['raw_response'][:200]}")
                self.logs.append(log_step(
                    step=len(self.logs) + 1, 
                    action="警告", 
                    description=f"AI返回格式错误，重试..."
                ))
                # 重试一次
                return await self._think_and_act(page, instruction, usage, step_count + 1, allow_manual_login)
            
            # 记录思考过程
            self.logs.append(log_step(
                step=len(self.logs) + 1, 
                action="思考", 
                description=thinking[:100] if thinking else description[:100]
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
                click_text = params.get("text", "")  # 新增：点击包含特定文本的元素
                if selector or click_text:
                    self.logs.append(log_step(step=len(self.logs) + 1, action="点击", description=description))
                    # 记录点击前的 URL
                    url_before = page.url
                    await self._do_click(page, selector, click_text)
                    # 等待页面加载完成或 URL 变化
                    try:
                        # 等待 URL 变化或网络空闲
                        for _ in range(10):
                            await asyncio.sleep(1)
                            if page.url != url_before:
                                logger.info(f"页面跳转: {url_before} -> {page.url}")
                                break
                        await page.wait_for_load_state("networkidle", timeout=15000)
                    except:
                        pass
                    await asyncio.sleep(self.wait_after_navigate)
                    # 记录点击后的 URL
                    logger.info(f"点击后 URL: {page.url}")
            
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
    
    async def _do_click(self, page, selector: str, click_text: str = ""):
        """执行点击操作
        
        Args:
            page: 页面对象
            selector: 选择器（nth(索引) 或 CSS）
            click_text: 要点击的元素包含的文本（优先使用）
        """
        try:
            # 优先使用文本匹配
            if click_text:
                # 尝试多种元素类型
                for element_type in ["button:visible", "a:visible", "[role='button']:visible", "div:visible", "span:visible", "input:visible"]:
                    try:
                        locator = page.locator(element_type).filter(has_text=click_text).first
                        await locator.click(timeout=3000)
                        logger.info(f"点击包含文本 '{click_text}' 的 {element_type} 成功")
                        await asyncio.sleep(self.wait_after_click)
                        return
                    except Exception as e:
                        continue
                
                # 尝试点击任意包含文本的可点击元素
                try:
                    locator = page.locator("*:visible").filter(has=page.locator(f"text={click_text}")).first
                    await locator.click(timeout=3000)
                    logger.info(f"点击包含文本 '{click_text}' 的元素成功")
                    await asyncio.sleep(self.wait_after_click)
                    return
                except Exception as e:
                    logger.warning(f"点击文本 '{click_text}' 失败: {str(e)}")
            
            # 使用选择器
            if selector.startswith("nth("):
                idx = int(selector.replace("nth(", "").replace(")", ""))
                # 获取所有可见可点击元素
                clickable = await page.locator("button:visible, a:visible, [role='button']:visible").all()
                if idx < len(clickable):
                    await clickable[idx].click()
                else:
                    await page.keyboard.press("Enter")
            elif selector:
                try:
                    await page.locator(selector).first.click(timeout=5000)
                except:
                    await page.locator("button:visible, a:visible").first.click()
            else:
                await page.keyboard.press("Enter")
            
            await asyncio.sleep(self.wait_after_click)
            
        except Exception as e:
            logger.warning(f"点击失败: {str(e)}")
            await page.keyboard.press("Enter")
    
    async def _get_interactive_elements(self, page) -> List[Dict]:
        """获取页面可交互元素 - 收集所有可见元素，让 AI 自己判断"""
        try:
            js_code = """
                () => {
                    const results = [];
                    
                    // 收集所有可交互元素
                    document.querySelectorAll('input:not([type="hidden"]), textarea, button, a, [role="button"], select').forEach((el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        
                        if (rect.width > 0 && rect.height > 0 && rect.top >= 0 &&
                            style.display !== 'none' && style.visibility !== 'hidden' && !el.disabled) {
                            
                            const tag = el.tagName.toLowerCase();
                            const type = el.type || '';
                            const text = (el.innerText || el.value || el.placeholder || '').substring(0, 30).trim();
                            const href = (el.href || '').substring(0, 50);
                            const placeholder = (el.placeholder || '').substring(0, 30);
                            
                            results.push({
                                tag: tag,
                                type: type,
                                text: text || placeholder || href,
                                href: href,
                                placeholder: placeholder
                            });
                        }
                    });
                    
                    return results.slice(0, %d);
                }
            """ % self.max_elements
            
            elements = await page.evaluate(js_code)
            
            if elements:
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
            # 移除 ```json 或 ```
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
                    except:
                        pass
        
        # 4. 尝试正则提取
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except:
                pass
        
        return {"raw_response": text}
