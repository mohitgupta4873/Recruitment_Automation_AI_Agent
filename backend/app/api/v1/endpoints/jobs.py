from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db, get_current_active_user
from app.core.database import User as UserModel, JobPost as JobPostModel
from app.schemas.job import (
    JobPostCreate, 
    JobPostResponse, 
    JobPostUpdate,
    LinkedInPostRequest,
    LinkedInPostResponse
)
from app.services.ai_service import ai_service
from app.services.linkedin_service import linkedin_service

router = APIRouter()

@router.post("/", response_model=JobPostResponse)
async def create_job_post(
    job_data: JobPostCreate,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Create a new job post and generate AI job description"""
    
    try:
        # Create job post record
        db_job = JobPostModel(
            user_id=current_user.id,
            role_request=job_data.role_request,
            requirements=job_data.requirements,
            google_form_link=job_data.google_form_link,
            status="DRAFT"
        )
        
        db.add(db_job)
        db.commit()
        db.refresh(db_job)
        
        # Generate AI job description
        jd_draft = ai_service.generate_job_description(job_data)
        
        # Update with generated JD
        db_job.jd_draft = jd_draft
        db_job.status = "DRAFTED"
        db.commit()
        db.refresh(db_job)
        
        return db_job
        
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create job post: {str(e)}"
        )

@router.get("/", response_model=List[JobPostResponse])
async def get_user_job_posts(
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get all job posts for the current user"""
    
    job_posts = db.query(JobPostModel).filter(
        JobPostModel.user_id == current_user.id
    ).order_by(JobPostModel.created_at.desc()).all()
    
    return job_posts

@router.get("/{job_id}", response_model=JobPostResponse)
async def get_job_post(
    job_id: int,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get a specific job post"""
    
    job_post = db.query(JobPostModel).filter(
        JobPostModel.id == job_id,
        JobPostModel.user_id == current_user.id
    ).first()
    
    if not job_post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job post not found"
        )
    
    return job_post

@router.put("/{job_id}", response_model=JobPostResponse)
async def update_job_post(
    job_id: int,
    job_update: JobPostUpdate,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update a job post"""
    
    job_post = db.query(JobPostModel).filter(
        JobPostModel.id == job_id,
        JobPostModel.user_id == current_user.id
    ).first()
    
    if not job_post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job post not found"
        )
    
    # Update fields
    for field, value in job_update.dict(exclude_unset=True).items():
        setattr(job_post, field, value)
    
    db.commit()
    db.refresh(job_post)
    
    return job_post

@router.post("/{job_id}/refine")
async def refine_job_description(
    job_id: int,
    feedback: str,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Refine job description based on feedback"""
    
    job_post = db.query(JobPostModel).filter(
        JobPostModel.id == job_id,
        JobPostModel.user_id == current_user.id
    ).first()
    
    if not job_post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job post not found"
        )
    
    if not job_post.jd_draft:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No job description to refine"
        )
    
    try:
        # Refine the job description
        refined_jd = ai_service.refine_job_description(
            job_post.jd_draft, 
            feedback
        )
        
        # Update the job post
        job_post.jd_draft = refined_jd
        job_post.status = "DRAFTED"
        db.commit()
        
        return {"message": "Job description refined successfully", "jd_draft": refined_jd}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refine job description: {str(e)}"
        )

@router.post("/{job_id}/approve")
async def approve_job_description(
    job_id: int,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Approve the job description"""
    
    job_post = db.query(JobPostModel).filter(
        JobPostModel.id == job_id,
        JobPostModel.user_id == current_user.id
    ).first()
    
    if not job_post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job post not found"
        )
    
    if not job_post.jd_draft:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No job description to approve"
        )
    
    # Set final JD and status
    job_post.final_jd = job_post.jd_draft
    job_post.status = "APPROVED"
    db.commit()
    
    return {"message": "Job description approved successfully"}

@router.post("/{job_id}/post-linkedin")
async def post_to_linkedin(
    job_id: int,
    linkedin_request: LinkedInPostRequest,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Post job description to LinkedIn"""
    
    job_post = db.query(JobPostModel).filter(
        JobPostModel.id == job_id,
        JobPostModel.user_id == current_user.id
    ).first()
    
    if not job_post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job post not found"
        )
    
    if job_post.status != "APPROVED":
        raise HTTPException(
            status_code=status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job description must be approved before posting to LinkedIn"
        )
    
    try:
        # Post to LinkedIn
        result = await linkedin_service.post_job_description(
            linkedin_request,
            job_post.final_jd,
            job_post.google_form_link
        )
        
        if result.success:
            # Update job post with LinkedIn information
            job_post.linkedin_post_id = result.post_id
            job_post.linkedin_post_url = result.post_url
            job_post.status = "POSTED"
            db.commit()
            
            return result
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.message
            )
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to post to LinkedIn: {str(e)}"
        )

@router.delete("/{job_id}")
async def delete_job_post(
    job_id: int,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete a job post"""
    
    job_post = db.query(JobPostModel).filter(
        JobPostModel.id == job_id,
        JobPostModel.user_id == current_user.id
    ).first()
    
    if not job_post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job post not found"
        )
    
    db.delete(job_post)
    db.commit()
    
    return {"message": "Job post deleted successfully"}
