"""
日志工具
"""
import logging
import sys
from datetime import datetime
from typing import List
from app.models.run import LogEntry


def get_logger(name: str = "agentweb") -> logging.Logger:
    """
    获取日志器
    
    Args:
        name: 日志器名称
    
    Returns:
        Logger 实例
    """
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    
    return logger


logger = get_logger()


def log_step(step: int, action: str, description: str) -> LogEntry:
    """
    创建日志条目
    
    Args:
        step: 步骤编号
        action: 动作类型
        description: 动作描述
    
    Returns:
        LogEntry 对象
    """
    entry = LogEntry(
        step=step,
        action=action,
        description=description,
        timestamp=datetime.now()
    )
    logger.info(f"[步骤 {step}] {action}: {description}")
    return entry


def log_request_info(instruction: str, model_name: str, headless: bool):
    """打印请求信息"""
    logger.info("=" * 50)
    logger.info("收到新任务请求")
    logger.info(f"指令: {instruction[:100]}...")
    logger.info(f"模型: {model_name}")
    logger.info(f"无头模式: {headless}")
    logger.info("=" * 50)


def log_response_info(success: bool, execution_time_ms: int, logs_count: int):
    """打印响应信息"""
    logger.info("=" * 50)
    logger.info(f"任务执行{'成功' if success else '失败'}")
    logger.info(f"执行耗时: {execution_time_ms}ms")
    logger.info(f"日志条数: {logs_count}")
    logger.info("=" * 50)