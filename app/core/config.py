"""
全局配置
"""
from typing import Optional
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """应用配置"""
    
    # 应用基础配置
    APP_NAME: str = "AgentWeb API"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    
    # API 配置
    API_V1_PREFIX: str = "/api/v1"
    
    # 默认 LLM 配置
    DEFAULT_BASE_URL: str = "https://api.openai.com/v1"
    DEFAULT_MODEL_NAME: str = "gpt-4o-mini"
    
    # 执行配置
    DEFAULT_TIMEOUT_SECONDS: int = 300
    DEFAULT_HEADLESS: bool = True
    
    # CORS 配置
    CORS_ORIGINS: list = ["*"]
    
    # 未来扩展：数据库配置
    # DATABASE_URL: Optional[str] = None
    
    # 未来扩展：Redis 缓存配置
    # REDIS_URL: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()