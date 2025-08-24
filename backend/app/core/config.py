from pydantic_settings import BaseSettings
from typing import List
import os

class Settings(BaseSettings):
    # API Keys
    GEMINI_API_KEY: str
    LINKEDIN_CLIENT_ID: str
    LINKEDIN_CLIENT_SECRET: str
    
    # Database
    DATABASE_URL: str
    DATABASE_TEST_URL: str = ""
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    
    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # App Settings
    DEBUG: bool = True
    ENVIRONMENT: str = "development"
    ALLOWED_HOSTS: List[str] = ["localhost", "127.0.0.1"]
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    
    # LinkedIn API
    LINKEDIN_REDIRECT_URI: str = "http://localhost:3000/auth/linkedin/callback"
    
    # AI Settings
    GEMINI_MODEL_NAME: str = "gemini-1.5-flash"
    MAX_JD_LENGTH: int = 1100
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
