web: gunicorn my_hiring_project.wsgi --workers 2 --timeout 120 --max-requests 500 --max-requests-jitter 50 --access-logfile - --error-logfile - --bind 0.0.0.0:$PORT
