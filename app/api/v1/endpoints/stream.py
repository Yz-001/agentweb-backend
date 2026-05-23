"""
流式任务执行端点 - SSE (Server-Sent Events)
实现实时日志推送
"""
import asyncio
import json
import time
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator

from app.models.run import RunRequest
from app.services.agent_executor import AgentExecutor
from app.core.exceptions import InvalidAPIKeyError, ExecutionError, TimeoutError
from app.utils.logger import log_request_info, logger

router = APIRouter()


@router.post("/stream")
async def run_task_stream(request: RunRequest):
    """
    流式执行网页自动化任务 (SSE)
    
    实时推送执行日志，客户端通过 EventSource 接收
    """
    # 验证参数
    if not request.instruction or not request.instruction.strip():
        raise HTTPException(
            status_code=400,
            detail={"success": False, "error": "指令不能为空", "error_type": "ValueError"}
        )
    
    if not request.api_key or not request.api_key.strip():
        raise HTTPException(
            status_code=401,
            detail={"success": False, "error": "API Key 不能为空", "error_type": "InvalidAPIKeyError"}
        )
    
    log_request_info(request.instruction, request.model_name, request.headless)
    
    async def event_generator() -> AsyncGenerator[str, None]:
        """SSE 事件生成器"""
        start_time = time.time()
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        
        # 创建日志队列
        log_queue: asyncio.Queue = asyncio.Queue()
        
        # 日志回调函数
        async def log_callback(log_data: dict):
            await log_queue.put(log_data)
        
        # 创建执行器（带日志回调）
        executor = AgentExecutor(
            api_key=request.api_key,
            base_url=request.base_url,
            model_name=request.model_name,
            headless=request.headless,
            log_callback=log_callback
        )
        
        # 启动任务
        task = asyncio.create_task(
            executor.run(
                instruction=request.instruction,
                timeout_seconds=request.timeout_seconds,
                allow_manual_login=request.allow_manual_login
            )
        )
        
        try:
            # 流式输出日志
            while True:
                try:
                    # 等待日志，超时 1 秒发送心跳
                    log_data = await asyncio.wait_for(log_queue.get(), timeout=1.0)
                    
                    # 发送 SSE 事件
                    yield f"data: {json.dumps(log_data, ensure_ascii=False)}\n\n"
                    
                    # 任务完成
                    if log_data.get("done"):
                        break
                        
                except asyncio.TimeoutError:
                    # 发送心跳保持连接
                    yield f": heartbeat\n\n"
                    
                    # 检查任务是否完成
                    if task.done():
                        break
                        
                except Exception as e:
                    logger.warning(f"SSE 日志处理错误: {str(e)}")
                    yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
                    break
            
            # 等待任务完成，获取最终结果
            try:
                result = await task
                execution_time_ms = int((time.time() - start_time) * 1000)
                
                # 发送最终结果
                final_data = {
                    "done": True,
                    "success": True,
                    "result": result.get("result", {}),
                    "execution_time_ms": execution_time_ms,
                    "usage": result.get("usage", usage),
                    "logs_count": len(result.get("logs", []))
                }
                yield f"data: {json.dumps(final_data, ensure_ascii=False)}\n\n"
                
            except TimeoutError as e:
                yield f"data: {json.dumps({'done': True, 'success': False, 'error': str(e), 'error_type': 'TimeoutError'}, ensure_ascii=False)}\n\n"
            except InvalidAPIKeyError as e:
                yield f"data: {json.dumps({'done': True, 'success': False, 'error': str(e), 'error_type': 'InvalidAPIKeyError'}, ensure_ascii=False)}\n\n"
            except ExecutionError as e:
                yield f"data: {json.dumps({'done': True, 'success': False, 'error': str(e), 'error_type': 'ExecutionError'}, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'done': True, 'success': False, 'error': str(e), 'error_type': 'UnknownError'}, ensure_ascii=False)}\n\n"
                
        except asyncio.CancelledError:
            # 客户端断开连接
            logger.info("SSE 连接已断开")
            task.cancel()
            raise
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # 禁用 nginx 缓冲
        }
    )