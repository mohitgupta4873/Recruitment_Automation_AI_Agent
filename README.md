# AI Job Posting Agent 🚀

An intelligent AI-powered platform that helps recruiters create compelling job descriptions and automatically post them on LinkedIn using advanced AI models.

## ✨ Features

- **AI-Powered Job Description Generation**: Uses Google Gemini AI to create professional, inclusive job descriptions
- **Interactive Feedback Loop**: Iterative refinement with recruiter feedback
- **LinkedIn Integration**: Automatic posting to LinkedIn with proper formatting
- **Modern Web Interface**: Beautiful, responsive frontend for seamless user experience
- **Smart Content Optimization**: Ensures LinkedIn character limits and formatting requirements
- **Professional Templates**: Pre-built templates for various job roles and industries

## 🏗️ Architecture

- **Frontend**: React.js with TypeScript, Tailwind CSS, and modern UI components
- **Backend**: FastAPI with Python, async support, and RESTful API design
- **AI Engine**: Google Gemini AI integration with LangGraph for workflow management
- **Database**: PostgreSQL for user management and job posting history
- **Authentication**: JWT-based secure authentication system
- **Deployment**: Docker containerization with CI/CD pipeline

## 🚀 Quick Start

### Prerequisites
- Python 3.9+
- Node.js 18+
- PostgreSQL
- Google Gemini API Key
- LinkedIn API Access

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/ai-job-posting-agent.git
cd ai-job-posting-agent
```

2. **Backend Setup**
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys
uvicorn main:app --reload
```

3. **Frontend Setup**
```bash
cd frontend
npm install
npm run dev
```

4. **Database Setup**
```bash
# Create database and run migrations
python manage.py db upgrade
```

## 🔧 Configuration

Create a `.env` file in the backend directory:

```env
GEMINI_API_KEY=your_gemini_api_key
LINKEDIN_CLIENT_ID=your_linkedin_client_id
LINKEDIN_CLIENT_SECRET=your_linkedin_client_secret
DATABASE_URL=postgresql://user:password@localhost/dbname
SECRET_KEY=your_secret_key
```

## 📱 Usage

1. **Login/Register**: Create an account or sign in
2. **Job Creation**: Input job role and requirements
3. **AI Generation**: Let AI create a professional job description
4. **Review & Refine**: Provide feedback for improvements
5. **LinkedIn Posting**: Automatically post to LinkedIn with one click

## 🛠️ Tech Stack

- **Frontend**: React, TypeScript, Tailwind CSS, Framer Motion
- **Backend**: FastAPI, Python, SQLAlchemy, Alembic
- **AI**: Google Gemini, LangGraph, Pydantic
- **Database**: PostgreSQL, Redis
- **Deployment**: Docker, GitHub Actions, Vercel/Railway

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Google Gemini AI for powerful language generation
- LinkedIn API for professional networking integration
- The open-source community for amazing tools and libraries

## 📞 Support

For support, email support@aijobagent.com or create an issue in this repository.
