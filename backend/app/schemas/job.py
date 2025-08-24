from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class JobPostBase(BaseModel):
    role_request: str
    requirements: Optional[str] = None
    google_form_link: Optional[str] = None

class JobPostCreate(JobPostBase):
    pass

class JobPostUpdate(BaseModel):
    requirements: Optional[str] = None
    jd_draft: Optional[str] = None
    final_jd: Optional[str] = None
    status: Optional[str] = None
    google_form_link: Optional[str] = None

class JobPostInDB(JobPostBase):
    id: int
    user_id: int
    jd_draft: Optional[str] = None
    final_jd: Optional[str] = None
    status: str
    linkedin_post_id: Optional[str] = None
    linkedin_post_url: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class JobPost(JobPostInDB):
    pass

class JobPostResponse(BaseModel):
    id: int
    role_request: str
    requirements: Optional[str] = None
    jd_draft: Optional[str] = None
    final_jd: Optional[str] = None
    status: str
    linkedin_post_id: Optional[str] = None
    linkedin_post_url: Optional[str] = None
    google_form_link: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

class LinkedInPostRequest(BaseModel):
    job_post_id: int
    access_token: str
    author_urn: str

class LinkedInPostResponse(BaseModel):
    success: bool
    post_id: Optional[str] = None
    post_url: Optional[str] = None
    message: str
