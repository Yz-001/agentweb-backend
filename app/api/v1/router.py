"""
API v1 总路由
"""
from fastapi import APIRouter
from app.api.v1.endpoints import run, health, stream

api_router = APIRouter()

# 注册各端点路由
api_router.include_router(health.router, prefix="/health", tags=["健康检查"])
api_router.include_router(run.router, prefix="/run", tags=["任务执行"])
api_router.include_router(stream.router, prefix="/run", tags=["流式任务执行"])
