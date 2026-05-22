"""
自定义异常
"""


class InvalidAPIKeyError(Exception):
    """API Key 无效错误"""
    pass


class ExecutionError(Exception):
    """执行错误"""
    pass


class TimeoutError(Exception):
    """超时错误"""
    pass


class RateLimitError(Exception):
    """频率限制错误"""
    pass


class TaskNotFoundError(Exception):
    """任务未找到错误（未来扩展）"""
    pass


class TemplateNotFoundError(Exception):
    """模板未找到错误（未来扩展）"""
    pass


class WorkflowNotFoundError(Exception):
    """工作流未找到错误（未来扩展）"""
    pass