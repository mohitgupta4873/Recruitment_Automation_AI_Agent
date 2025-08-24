# 🚀 Quick Railway Deployment

## ⚡ 5-Minute Deployment

### 1. **Go to Railway**
- Visit: [railway.app](https://railway.app)
- Sign in with GitHub

### 2. **Create New Project**
- Click "New Project"
- Select "Deploy from GitHub repo"
- Choose: `mohitgupta4873/Project-ai-agent`

### 3. **Set Environment Variables**
Copy these into Railway's environment variables section:

```bash
# AI API Keys (Required)
GEMINI_API_KEY=your_gemini_api_key_here
LINKEDIN_CLIENT_ID=your_linkedin_client_id
LINKEDIN_CLIENT_SECRET=your_linkedin_client_secret

# Security
SECRET_KEY=your_random_secret_key_here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# App Settings
DEBUG=false
ENVIRONMENT=production
ALLOWED_HOSTS=*
CORS_ORIGINS=*
```

### 4. **Deploy**
- Click "Deploy"
- Wait 2-5 minutes
- Get your public URL!

## 🎯 Your App Will Be Available At:
`https://your-app-name.railway.app`

## 📱 Test Your AI Agent:
1. Visit your Railway URL
2. Register a new account
3. Create a job posting
4. Let AI generate the description
5. Post to LinkedIn!

---

**Need API Keys?**
- **Gemini:** [Google AI Studio](https://makersuite.google.com/app/apikey)
- **LinkedIn:** [LinkedIn Developer Portal](https://developer.linkedin.com/)
