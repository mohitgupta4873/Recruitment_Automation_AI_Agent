# Project Structure 📁

This document provides an overview of the AI Job Posting Agent project structure.

## 🏗️ Overall Architecture

```
ai-job-posting-agent/
├── backend/                 # FastAPI Backend
├── frontend/               # Next.js Frontend
├── .github/                # GitHub Actions CI/CD
├── docs/                   # Documentation
├── scripts/                # Utility scripts
└── deployment/             # Deployment configurations
```

## 🔧 Backend Structure

```
backend/
├── app/
│   ├── api/               # API endpoints
│   │   └── v1/
│   │       ├── api.py     # Main API router
│   │       └── endpoints/ # Route handlers
│   │           ├── auth.py    # Authentication endpoints
│   │           ├── jobs.py    # Job management endpoints
│   │           └── users.py   # User management endpoints
│   ├── core/              # Core functionality
│   │   ├── config.py      # Configuration settings
│   │   ├── database.py    # Database models & connection
│   │   └── auth.py        # Authentication utilities
│   ├── schemas/           # Pydantic models
│   │   ├── user.py        # User schemas
│   │   └── job.py         # Job schemas
│   └── services/          # Business logic
│       ├── ai_service.py      # AI job description generation
│       └── linkedin_service.py # LinkedIn API integration
├── main.py                # FastAPI application entry point
├── requirements.txt       # Python dependencies
└── env.example           # Environment variables template
```

## 🎨 Frontend Structure

```
frontend/
├── app/                   # Next.js 13+ app directory
│   ├── auth/             # Authentication pages
│   │   ├── login/        # Login page
│   │   └── register/     # Registration page
│   ├── dashboard/        # Main dashboard
│   ├── globals.css       # Global styles
│   ├── layout.tsx        # Root layout
│   └── page.tsx          # Landing page
├── components/            # Reusable components
│   ├── JobPostForm.tsx   # Job creation form
│   ├── JobPostCard.tsx   # Job post display card
│   └── ui/               # UI components
├── lib/                   # Utility functions
├── package.json           # Node.js dependencies
├── tailwind.config.js     # Tailwind CSS configuration
└── next.config.js         # Next.js configuration
```

## 🐳 Docker Configuration

```
├── Dockerfile             # Multi-stage production build
├── docker-compose.yml     # Local development & production
└── nginx/                 # Reverse proxy configuration
    ├── nginx.conf         # Nginx configuration
    └── ssl/               # SSL certificates
```

## 🚀 CI/CD & Deployment

```
.github/
└── workflows/
    └── ci-cd.yml         # GitHub Actions pipeline

deployment/
├── kubernetes/            # Kubernetes manifests
├── terraform/             # Infrastructure as Code
└── scripts/               # Deployment scripts
```

## 📚 Documentation

```
├── README.md              # Project overview & setup
├── DEPLOYMENT.md          # Deployment guide
├── PROJECT_STRUCTURE.md   # This file
├── API_DOCUMENTATION.md   # API reference
└── CONTRIBUTING.md        # Contribution guidelines
```

## 🔑 Key Features

### Backend Features
- **FastAPI**: Modern, fast web framework
- **PostgreSQL**: Reliable database
- **Redis**: Caching layer
- **JWT Authentication**: Secure user management
- **AI Integration**: Google Gemini API
- **LinkedIn API**: Job posting automation
- **Async Support**: High-performance async operations

### Frontend Features
- **Next.js 13+**: React framework with app directory
- **TypeScript**: Type-safe development
- **Tailwind CSS**: Utility-first styling
- **Framer Motion**: Smooth animations
- **Responsive Design**: Mobile-first approach
- **Modern UI/UX**: Professional interface

### DevOps Features
- **Docker**: Containerization
- **GitHub Actions**: Automated CI/CD
- **Multi-stage Builds**: Optimized production images
- **Health Checks**: Application monitoring
- **Security Scanning**: Vulnerability detection

## 🗄️ Database Schema

### Users Table
- `id`: Primary key
- `email`: Unique email address
- `username`: Unique username
- `hashed_password`: Encrypted password
- `full_name`: User's full name
- `company`: Company name
- `is_active`: Account status
- `created_at`: Account creation timestamp
- `updated_at`: Last update timestamp

### Job Posts Table
- `id`: Primary key
- `user_id`: Foreign key to users
- `role_request`: Job role description
- `requirements`: Job requirements
- `jd_draft`: AI-generated draft
- `final_jd`: Approved job description
- `status`: Current status (DRAFT, APPROVED, POSTED)
- `linkedin_post_id`: LinkedIn post identifier
- `linkedin_post_url`: LinkedIn post URL
- `google_form_link`: Application form link
- `created_at`: Creation timestamp
- `updated_at`: Last update timestamp

### LinkedIn Credentials Table
- `id`: Primary key
- `user_id`: Foreign key to users
- `access_token`: LinkedIn access token
- `refresh_token`: LinkedIn refresh token
- `expires_at`: Token expiration
- `author_urn`: LinkedIn author identifier
- `created_at`: Creation timestamp
- `updated_at`: Last update timestamp

## 🔄 API Endpoints

### Authentication
- `POST /api/v1/auth/register` - User registration
- `POST /api/v1/auth/login` - User login
- `GET /api/v1/auth/me` - Get current user
- `POST /api/v1/auth/refresh` - Refresh token

### Job Management
- `POST /api/v1/jobs/` - Create job post
- `GET /api/v1/jobs/` - List user's jobs
- `GET /api/v1/jobs/{id}` - Get specific job
- `PUT /api/v1/jobs/{id}` - Update job
- `DELETE /api/v1/jobs/{id}` - Delete job
- `POST /api/v1/jobs/{id}/refine` - Refine with AI
- `POST /api/v1/jobs/{id}/approve` - Approve job
- `POST /api/v1/jobs/{id}/post-linkedin` - Post to LinkedIn

### User Management
- `GET /api/v1/users/profile` - Get user profile
- `PUT /api/v1/users/profile` - Update profile
- `DELETE /api/v1/users/profile` - Deactivate account

## 🚀 Getting Started

1. **Clone the repository**
   ```bash
   git clone <your-repo-url>
   cd ai-job-posting-agent
   ```

2. **Quick start with Docker**
   ```bash
   # Windows
   quick-start.bat
   
   # Unix/Linux/macOS
   ./quick-start.sh
   ```

3. **Manual setup**
   ```bash
   # Backend
   cd backend
   pip install -r requirements.txt
   cp env.example .env
   # Edit .env with your API keys
   uvicorn main:app --reload
   
   # Frontend
   cd frontend
   npm install
   npm run dev
   ```

## 🔧 Development

### Backend Development
- **Virtual Environment**: Use `python -m venv venv`
- **Code Formatting**: Use `black` and `isort`
- **Linting**: Use `flake8` and `mypy`
- **Testing**: Use `pytest` with coverage

### Frontend Development
- **Code Formatting**: Use `prettier`
- **Linting**: Use `eslint`
- **Type Checking**: Use `tsc --noEmit`
- **Testing**: Use `jest` and `@testing-library/react`

## 📊 Monitoring & Logging

- **Health Checks**: `/health` endpoint
- **API Documentation**: `/docs` (Swagger UI)
- **Logging**: Structured logging with correlation IDs
- **Metrics**: Performance monitoring endpoints
- **Error Tracking**: Centralized error handling

## 🔒 Security

- **JWT Tokens**: Secure authentication
- **Password Hashing**: bcrypt encryption
- **CORS**: Cross-origin resource sharing
- **Rate Limiting**: API request throttling
- **Input Validation**: Pydantic schema validation
- **SQL Injection**: SQLAlchemy ORM protection

## 📈 Performance

- **Async Operations**: Non-blocking I/O
- **Database Indexing**: Optimized queries
- **Caching**: Redis-based caching
- **Connection Pooling**: Database connection management
- **Compression**: Gzip response compression

## 🌐 Deployment Options

1. **Docker Compose**: Local development
2. **Railway**: Cloud platform deployment
3. **Vercel**: Frontend hosting
4. **Render**: Full-stack hosting
5. **Kubernetes**: Container orchestration
6. **AWS/GCP/Azure**: Cloud provider deployment

## 📞 Support & Contributing

- **Issues**: GitHub Issues for bug reports
- **Discussions**: GitHub Discussions for questions
- **Contributing**: See CONTRIBUTING.md
- **Code of Conduct**: Community guidelines
- **License**: MIT License
