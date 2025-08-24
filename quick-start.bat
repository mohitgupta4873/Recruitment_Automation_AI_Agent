@echo off
echo 🚀 AI Job Posting Agent - Quick Start Script
echo ==============================================

REM Check if Docker is installed
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Docker is not installed. Please install Docker first.
    echo Visit: https://docs.docker.com/get-docker/
    pause
    exit /b 1
)

REM Check if Docker Compose is installed
docker-compose --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Docker Compose is not installed. Please install Docker Compose first.
    echo Visit: https://docs.docker.com/compose/install/
    pause
    exit /b 1
)

echo ✅ Docker and Docker Compose are installed

REM Create environment file if it doesn't exist
if not exist "backend\.env" (
    echo 📝 Creating environment file...
    copy "backend\env.example" "backend\.env"
    echo ⚠️  Please edit backend\.env with your actual API keys and database credentials
    echo    Required: GEMINI_API_KEY, LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET
    echo    Press any key when ready to continue...
    pause >nul
) else (
    echo ✅ Environment file already exists
)

REM Start the application
echo 🐳 Starting the application with Docker Compose...
docker-compose up -d

REM Wait for services to be ready
echo ⏳ Waiting for services to start...
timeout /t 30 /nobreak >nul

REM Check if services are running
echo 🔍 Checking service status...
docker-compose ps

echo.
echo 🎉 Setup complete! Your application should be running at:
echo    Frontend: http://localhost:3000
echo    Backend API: http://localhost:8000
echo    API Documentation: http://localhost:8000/docs
echo.
echo 📚 Next steps:
echo    1. Open http://localhost:3000 in your browser
echo    2. Create an account or sign in
echo    3. Start creating AI-powered job descriptions!
echo.
echo 🛠️  Useful commands:
echo    View logs: docker-compose logs -f
echo    Stop services: docker-compose down
echo    Restart: docker-compose restart
echo    Update: git pull ^&^& docker-compose up -d --build
echo.
echo 📖 For more information, see README.md and DEPLOYMENT.md
pause
