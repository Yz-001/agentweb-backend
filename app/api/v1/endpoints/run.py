"""
任务执行端点
"""
import time
from fastapi import APIRouter, HTTPException

from app.models.run import RunRequest, RunResponse, ErrorResponse
from app.services.agent_executor import AgentExecutor
from app.core.exceptions import InvalidAPIKeyError, ExecutionError, TimeoutError
from app.utils.logger import log_request_info, log_response_info

router = APIRouter()


@router.post("", response_model=RunResponse, responses={
    400: {"model": ErrorResponse},
    401: {"model": ErrorResponse},
    408: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
    500: {"model": ErrorResponse}
})
async def run_task(request: RunRequest):
    """
    执行网页自动化任务
    
    接收自然语言指令，驱动浏览器执行任务，返回结果和日志。
    """
    start_time = time.time()
    logs = []
    
    # 打印请求信息
    log_request_info(request.instruction, request.model_name, request.headless)
    
    try:
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
        
        # 创建执行器
        executor = AgentExecutor(
            api_key=request.api_key,
            base_url=request.base_url,
            model_name=request.model_name,
            headless=request.headless
        )
        
        # 执行任务
        result_data = await executor.run(
            instruction=request.instruction,
            timeout_seconds=request.timeout_seconds,
            allow_manual_login=request.allow_manual_login
        )
        
        # 计算执行耗时
        execution_time_ms = int((time.time() - start_time) * 1000)
        
        # 构建响应
        response = RunResponse(
            success=True,
            result=result_data.get("result", {}),
            logs=result_data.get("logs", []),
            execution_time_ms=execution_time_ms,
            usage=result_data.get("usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        )
        
        log_response_info(True, execution_time_ms, len(response.logs))
        
        return response
        
    except TimeoutError as e:
        execution_time_ms = int((time.time() - start_time) * 1000)
        log_response_info(False, execution_time_ms, 0)
        raise HTTPException(
            status_code=408,
            detail={
                "success": False,
                "error": str(e),
                "error_type": "TimeoutError",
                "logs": logs
            }
        )
    
    except InvalidAPIKeyError as e:
        execution_time_ms = int((time.time() - start_time) * 1000)
        log_response_info(False, execution_time_ms, 0)
        raise HTTPException(
            status_code=401,
            detail={
                "success": False,
                "error": str(e),
                "error_type": "InvalidAPIKeyError",
                "logs": logs
            }
        )
    
    except ExecutionError as e:
        execution_time_ms = int((time.time() - start_time) * 1000)
        log_response_info(False, execution_time_ms, 0)
        
        error_str = str(e)
        
        # 判断是否是 rate limit 错误
        if "rate limit" in error_str.lower() or "429" in error_str:
            status_code = 429
        # 判断是否是输入长度超限错误
        elif "input length" in error_str.lower() or "3072" in error_str or "context length" in error_str.lower():
            status_code = 400
            error_str = f"输入长度超出模型限制。当前模型可能不支持长输入，请切换到支持长上下文的模型（如 gpt-4o-mini、deepseek-chat、qwen-max）。原始错误: {error_str}"
        else:
            status_code = 500
        
        raise HTTPException(
            status_code=status_code,
            detail={
                "success": False,
                "error": error_str,
                "error_type": "ExecutionError",
                "logs": logs
            }
        )
    
    except ValueError as e:
        execution_time_ms = int((time.time() - start_time) * 1000)
        log_response_info(False, execution_time_ms, 0)
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "error": str(e),
                "error_type": "ValueError",
                "logs": logs
            }
        )
    
    except HTTPException:
        raise
    
    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)
        log_response_info(False, execution_time_ms, 0)
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "error": f"服务器内部错误: {str(e)}",
                "error_type": "InternalServerError",
                "logs": logs
            }
        )