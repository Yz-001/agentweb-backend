"""
运行任务相关的 Pydantic 模型
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    """运行任务请求模型"""
    instruction: str = Field(..., description="自然语言指令")
    api_key: str = Field(..., description="OpenAI 兼容的 API Key")
    base_url: Optional[str] = Field(
        default="https://api.openai.com/v1",
        description="API Base URL"
    )
    model_name: Optional[str] = Field(
        default="gpt-4o-mini",
        description="模型名称"
    )
    headless: Optional[bool] = Field(
        default=True,
        description="是否无头模式运行浏览器"
    )
    timeout_seconds: Optional[int] = Field(
        default=300,
        description="任务超时时间（秒）"
    )
    allow_manual_login: Optional[bool] = Field(
        default=False,
        description="是否允许手动登录（非 headless 模式下检测到登录页面时等待用户处理）"
    )


class LogEntry(BaseModel):
    """执行日志条目"""
    step: int = Field(..., description="步骤编号")
    action: str = Field(..., description="动作类型")
    description: str = Field(..., description="动作描述")
    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")


class RunResponse(BaseModel):
    """成功响应模型"""
    success: bool = Field(default=True, description="是否成功")
    result: Dict[str, Any] = Field(default_factory=dict, description="Agent 返回的结构化数据")
    logs: List[LogEntry] = Field(default_factory=list, description="执行日志列表")
    execution_time_ms: int = Field(..., description="执行耗时（毫秒）")
    usage: Dict[str, int] = Field(
        default_factory=lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        description="Token 使用量"
    )


class ErrorResponse(BaseModel):
    """错误响应模型"""
    success: bool = Field(default=False, description="是否成功")
    error: str = Field(..., description="错误信息")
    error_type: str = Field(..., description="错误类型")
    logs: Optional[List[LogEntry]] = Field(default=None, description="执行日志（可能部分存在）")