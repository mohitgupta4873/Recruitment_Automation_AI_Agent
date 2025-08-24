import google.generativeai as genai
import textwrap
from typing import Optional
from app.core.config import settings
from app.schemas.job import JobPostCreate

class AIService:
    def __init__(self):
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(settings.GEMINI_MODEL_NAME)
    
    def generate_job_description(self, job_request: JobPostCreate, feedback: Optional[str] = None) -> str:
        """Generate a job description using Google Gemini AI"""
        
        prompt = self._build_prompt(job_request, feedback)
        
        try:
            response = self.model.generate_content(prompt)
            jd_text = (response.text or "").strip()
            
            if not jd_text:
                raise ValueError("Empty JD draft from model.")
                
            return jd_text
            
        except Exception as e:
            raise Exception(f"Failed to generate JD: {str(e)}")
    
    def _build_prompt(self, job_request: JobPostCreate, feedback: Optional[str] = None) -> str:
        """Build a structured prompt for Gemini to generate a high-quality JD"""
        
        role = job_request.role_request.strip()
        reqs = job_request.requirements or ""
        
        base_instructions = f"""
        You are an expert technical recruiter. Create a clear, inclusive, and concise Job Description in **Markdown**.

        ROLE: {role or "[MISSING]"}
        KNOWN REQUIREMENTS (if any): {reqs or "—"}

        OUTPUT FORMAT (Markdown headings):
        # Job Title
        ## About the Role
        ## Responsibilities
        ## Must-Have Qualifications
        ## Good-to-Have Qualifications
        ## Tech Stack
        ## Impact & Growth
        ## Compensation & Benefits
        ## Location & Work Setup
        ## Interview Process
        ## How to Apply

        STYLE:
        - Inclusive, jargon-light, outcome-focused, use nice styling, bold the headlines wherever required.
        - Bullet points where it helps readability.
        - Avoid bias or age/college prestige signals; focus on skills/impact.
        - Keep it strictly {settings.MAX_JD_LENGTH} characters.
        - Don't be too monotonic and machinic in tone, be a little quirky, don't make such rigid and structured JD, instead make something eye-catching and worth attention

        NO PLACEHOLDERS WHATSOEVER:
        - The JD shouldn't have any unknown piece of information, assume anything that you find missing
        """
        
        feedback_block = f"\nRECRUITER FEEDBACK TO INCORPORATE:\n{feedback}\n" if feedback else ""
        return textwrap.dedent(base_instructions + feedback_block).strip()
    
    def refine_job_description(self, current_jd: str, feedback: str) -> str:
        """Refine existing job description based on feedback"""
        
        prompt = f"""
        You are an expert technical recruiter. Refine the following job description based on the feedback provided.

        CURRENT JOB DESCRIPTION:
        {current_jd}

        FEEDBACK TO INCORPORATE:
        {feedback}

        Please provide the refined job description in the same format, incorporating all the feedback while maintaining the professional structure and keeping it within {settings.MAX_JD_LENGTH} characters.
        """
        
        try:
            response = self.model.generate_content(prompt)
            refined_jd = (response.text or "").strip()
            
            if not refined_jd:
                raise ValueError("Empty refined JD from model.")
                
            return refined_jd
            
        except Exception as e:
            raise Exception(f"Failed to refine JD: {str(e)}")
    
    def optimize_for_linkedin(self, jd: str) -> str:
        """Optimize job description for LinkedIn posting"""
        
        prompt = f"""
        Optimize the following job description for LinkedIn posting. LinkedIn has a character limit of approximately 1300 characters for posts.

        JOB DESCRIPTION:
        {jd}

        Please provide a LinkedIn-optimized version that:
        1. Fits within 1100 characters (leaving room for hashtags and call-to-action)
        2. Uses LinkedIn-friendly formatting
        3. Includes relevant hashtags
        4. Has a compelling call-to-action
        5. Maintains all key information in a concise format
        """
        
        try:
            response = self.model.generate_content(prompt)
            optimized_jd = (response.text or "").strip()
            
            if not optimized_jd:
                raise ValueError("Empty optimized JD from model.")
                
            return optimized_jd
            
        except Exception as e:
            raise Exception(f"Failed to optimize JD for LinkedIn: {str(e)}")

# Create global instance
ai_service = AIService()
