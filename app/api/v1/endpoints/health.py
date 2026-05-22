"""
健康检查端点
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("")
async def health_check():
    """健康检查接口"""
    return {"status": "ok"}