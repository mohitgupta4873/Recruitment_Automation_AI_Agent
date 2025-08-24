# 🚀 Railway Deployment Guide

## Quick Deploy to Railway (No Docker Required!)

### Step 1: Prepare Your Repository
✅ Your repository is already ready with all the necessary files!

### Step 2: Deploy to Railway
1. **Visit [railway.app](https://railway.app)**
2. **Sign in with GitHub**
3. **Click "New Project"**
4. **Select "Deploy from GitHub repo"**
5. **Choose your repository: `mohitgupta4873/Project-ai-agent`**

### Step 3: Configure Environment Variables
Railway will ask you to set these environment variables:

```env
# Required: AI API Keys
GEMINI_API_KEY=your_gemini_api_key_here
LINKEDIN_CLIENT_ID=your_linkedin_client_id
LINKEDIN_CLIENT_SECRET=your_linkedin_client_secret

# Database (Railway will provide this)
DATABASE_URL=postgresql://username:password@host:port/database

# Security
SECRET_KEY=your_secret_key_here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# App Settings
DEBUG=false
ENVIRONMENT=production
ALLOWED_HOSTS=*
CORS_ORIGINS=*
```

### Step 4: Deploy
1. **Click "Deploy"**
2. **Wait for build to complete (2-5 minutes)**
3. **Railway will give you a public URL**

### Step 5: Access Your App
- **Backend API:** `https://your-app-name.railway.app`
- **Frontend:** Will be accessible via the same URL

## 🎯 What Happens Next?

Railway will automatically:
- Install Python dependencies
- Set up PostgreSQL database
- Deploy your FastAPI backend
- Provide a public HTTPS URL
- Handle SSL certificates

## 🔍 Troubleshooting

If you encounter issues:
1. Check the build logs in Railway dashboard
2. Verify environment variables are set correctly
3. Ensure your API keys are valid

## 📱 Test Your Deployment

Once deployed, you can:
1. Visit your Railway URL
2. Test the API endpoints
3. Use the AI agent to generate job descriptions
4. Post to LinkedIn (with valid credentials)

---

**Need Help?** Check the Railway logs or ask for assistance!
