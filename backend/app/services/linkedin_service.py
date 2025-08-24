import httpx
import json
from typing import Optional, Dict, Any
from app.core.config import settings
from app.schemas.job import LinkedInPostRequest, LinkedInPostResponse

class LinkedInService:
    def __init__(self):
        self.base_url = "https://api.linkedin.com/v2"
        self.headers = {
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0"
        }
    
    async def post_job_description(
        self, 
        request: LinkedInPostRequest, 
        job_description: str,
        google_form_link: Optional[str] = None
    ) -> LinkedInPostResponse:
        """Post job description to LinkedIn"""
        
        try:
            # Set authorization header
            headers = {
                **self.headers,
                "Authorization": f"Bearer {request.access_token}"
            }
            
            # Build post content
            post_content = self._build_post_content(
                job_description, 
                google_form_link
            )
            
            # LinkedIn post payload
            payload = {
                "author": request.author_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": post_content},
                        "shareMediaCategory": "NONE"
                    }
                },
                "visibility": {
                    "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
                }
            }
            
            # Make API call
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/ugcPosts",
                    headers=headers,
                    json=payload,
                    timeout=30.0
                )
            
            if response.status_code in (200, 201):
                data = response.json()
                post_id = data.get("id")
                post_url = f"https://www.linkedin.com/feed/update/{post_id}" if post_id else None
                
                return LinkedInPostResponse(
                    success=True,
                    post_id=post_id,
                    post_url=post_url,
                    message="Successfully posted to LinkedIn"
                )
            else:
                return LinkedInPostResponse(
                    success=False,
                    message=f"LinkedIn API error: {response.status_code} - {response.text}"
                )
                
        except Exception as e:
            return LinkedInPostResponse(
                success=False,
                message=f"Failed to post to LinkedIn: {str(e)}"
            )
    
    def _build_post_content(self, job_description: str, google_form_link: Optional[str] = None) -> str:
        """Build LinkedIn post content with proper formatting"""
        
        # LinkedIn post character limit is around 1300
        max_post_length = 1100  # Leave room for hashtags and formatting
        
        # Start with job announcement
        initial_text = "🚀 We're hiring! Check out this exciting opportunity:\n\n"
        
        # Add form link if provided
        if google_form_link:
            initial_text += f"📝 Apply here: {google_form_link}\n\n"
        
        # Calculate remaining length for job description
        remaining_length = max_post_length - len(initial_text)
        
        # Truncate job description if needed
        if len(job_description) > remaining_length:
            # Find a good truncation point (end of a sentence or section)
            truncated_jd = job_description[:remaining_length - 4] + "..."
        else:
            truncated_jd = job_description
        
        # Build final post content
        post_content = initial_text + truncated_jd
        
        # Add relevant hashtags
        hashtags = "\n\n#hiring #jobopportunity #careers #techjobs #remotework"
        post_content += hashtags
        
        return post_content
    
    async def validate_access_token(self, access_token: str) -> bool:
        """Validate LinkedIn access token"""
        try:
            headers = {
                **self.headers,
                "Authorization": f"Bearer {access_token}"
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/me",
                    headers=headers,
                    timeout=10.0
                )
            
            return response.status_code == 200
            
        except Exception:
            return False
    
    async def get_user_profile(self, access_token: str) -> Optional[Dict[str, Any]]:
        """Get LinkedIn user profile information"""
        try:
            headers = {
                **self.headers,
                "Authorization": f"Bearer {access_token}"
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/me",
                    headers=headers,
                    timeout=10.0
                )
            
            if response.status_code == 200:
                return response.json()
            return None
            
        except Exception:
            return None

# Create global instance
linkedin_service = LinkedInService()
