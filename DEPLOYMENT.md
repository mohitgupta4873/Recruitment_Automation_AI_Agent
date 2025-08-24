# Deployment Guide 🚀

This guide covers deploying the AI Job Posting Agent to various platforms.

## 🐳 Docker Deployment

### Prerequisites
- Docker and Docker Compose installed
- PostgreSQL and Redis (or use the provided Docker services)

### Quick Start with Docker Compose

1. **Clone and setup**
```bash
git clone <your-repo-url>
cd ai-job-posting-agent
```

2. **Environment Configuration**
```bash
# Copy environment file
cp backend/env.example backend/.env

# Edit with your actual values
nano backend/.env
```

3. **Start the application**
```bash
# Development mode
docker-compose up -d

# Production mode
docker-compose --profile production up -d
```

4. **Access the application**
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

### Production Docker Deployment

1. **Build production image**
```bash
docker build -t ai-job-posting-agent:latest .
```

2. **Run with production environment**
```bash
docker run -d \
  --name ai-job-agent \
  -p 8000:8000 \
  --env-file backend/.env \
  ai-job-posting-agent:latest
```

## ☁️ Cloud Deployment

### Railway Deployment

1. **Install Railway CLI**
```bash
npm install -g @railway/cli
```

2. **Login and deploy**
```bash
railway login
railway init
railway up
```

3. **Set environment variables**
```bash
railway variables set GEMINI_API_KEY=your_key
railway variables set DATABASE_URL=your_db_url
# ... other variables
```

### Vercel Deployment (Frontend)

1. **Install Vercel CLI**
```bash
npm install -g vercel
```

2. **Deploy frontend**
```bash
cd frontend
vercel --prod
```

3. **Configure environment variables in Vercel dashboard**

### Render Deployment

1. **Create new Web Service**
2. **Connect your GitHub repository**
3. **Configure build settings**
4. **Set environment variables**
5. **Deploy**

## 🐙 GitHub Actions Deployment

### Setup Secrets

Add these secrets to your GitHub repository:

```bash
# Docker Hub
DOCKER_USERNAME=your_username
DOCKER_PASSWORD=your_password

# API Keys
GEMINI_API_KEY=your_gemini_key
LINKEDIN_CLIENT_ID=your_linkedin_id
LINKEDIN_CLIENT_SECRET=your_linkedin_secret

# Database
DATABASE_URL=your_production_db_url
SECRET_KEY=your_secret_key
```

### Automatic Deployment

The CI/CD pipeline will:
1. Run tests on push/PR
2. Build Docker image on main branch
3. Deploy to production automatically

## 🗄️ Database Setup

### PostgreSQL

1. **Create database**
```sql
CREATE DATABASE ai_job_agent;
CREATE USER ai_user WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE ai_job_agent TO ai_user;
```

2. **Run migrations**
```bash
cd backend
alembic upgrade head
```

### Redis

1. **Install Redis**
```bash
# Ubuntu/Debian
sudo apt install redis-server

# macOS
brew install redis
```

2. **Start Redis service**
```bash
sudo systemctl start redis-server
```

## 🔐 Environment Variables

### Required Variables

```env
# API Keys
GEMINI_API_KEY=your_gemini_api_key
LINKEDIN_CLIENT_ID=your_linkedin_client_id
LINKEDIN_CLIENT_SECRET=your_linkedin_client_secret

# Database
DATABASE_URL=postgresql://user:password@host:port/dbname

# Security
SECRET_KEY=your_secret_key_here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# App Settings
DEBUG=False
ENVIRONMENT=production
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
```

### Optional Variables

```env
# Redis
REDIS_URL=redis://localhost:6379

# LinkedIn API
LINKEDIN_REDIRECT_URI=https://yourdomain.com/auth/linkedin/callback

# AI Settings
GEMINI_MODEL_NAME=gemini-1.5-flash
MAX_JD_LENGTH=1100
```

## 📊 Monitoring & Health Checks

### Health Check Endpoint
- URL: `/health`
- Returns: Application status and version

### Logging
- Backend logs: Check Docker logs or application logs
- Frontend logs: Browser console and Vercel/Railway logs

### Performance Monitoring
- Use tools like New Relic, DataDog, or built-in monitoring
- Monitor API response times and database performance

## 🔒 Security Considerations

### Production Security
1. **HTTPS**: Always use HTTPS in production
2. **Environment Variables**: Never commit secrets to version control
3. **Database**: Use strong passwords and limit access
4. **API Keys**: Rotate keys regularly
5. **Rate Limiting**: Implement rate limiting for API endpoints

### SSL/TLS Setup
```bash
# Generate SSL certificate
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes

# Configure Nginx with SSL
# See nginx/nginx.conf for example configuration
```

## 🚨 Troubleshooting

### Common Issues

1. **Database Connection Failed**
   - Check DATABASE_URL format
   - Verify database is running
   - Check firewall settings

2. **API Key Errors**
   - Verify GEMINI_API_KEY is set
   - Check API key permissions
   - Ensure key is not expired

3. **LinkedIn Integration Issues**
   - Verify LinkedIn app credentials
   - Check redirect URI configuration
   - Ensure proper OAuth scopes

4. **Frontend Build Errors**
   - Check Node.js version (requires 18+)
   - Clear npm cache: `npm cache clean --force`
   - Delete node_modules and reinstall

### Debug Mode

Enable debug mode for troubleshooting:
```env
DEBUG=True
LOG_LEVEL=DEBUG
```

## 📈 Scaling

### Horizontal Scaling
1. **Load Balancer**: Use Nginx or cloud load balancer
2. **Multiple Instances**: Deploy multiple backend instances
3. **Database**: Consider read replicas for heavy traffic

### Vertical Scaling
1. **Resources**: Increase CPU/memory allocation
2. **Database**: Optimize database queries and indexes
3. **Caching**: Implement Redis caching for frequently accessed data

## 🔄 Updates & Maintenance

### Regular Maintenance
1. **Security Updates**: Keep dependencies updated
2. **Database Backups**: Regular automated backups
3. **Monitoring**: Monitor application health and performance
4. **Log Rotation**: Implement log rotation to manage disk space

### Update Process
1. **Staging**: Test updates in staging environment
2. **Backup**: Backup production data before updates
3. **Rollback Plan**: Have rollback strategy ready
4. **Zero-Downtime**: Use blue-green deployment when possible

## 📞 Support

For deployment issues:
1. Check the troubleshooting section
2. Review application logs
3. Verify environment configuration
4. Create an issue in the GitHub repository

## 🎯 Next Steps

After successful deployment:
1. Set up monitoring and alerting
2. Configure automated backups
3. Implement CI/CD for your specific deployment target
4. Set up staging environment for testing
5. Document your deployment process
