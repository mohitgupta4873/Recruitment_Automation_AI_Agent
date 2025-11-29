from django.shortcuts import render, redirect
from django.conf import settings
from .services import HiringAutomator
import os

# Helper to initialize service
def get_automator():
    # Looks for token.json in the project root
    token_path = os.path.join(settings.BASE_DIR, 'token.json')
    state_path = os.path.join(settings.BASE_DIR, 'campaign_state.json')
    return HiringAutomator(token_path, state_path)

def dashboard(request):
    try:
        automator = get_automator()
        state = automator.load_state()
    except Exception as e:
        # Pass empty state if file read fails
        state = {}
        # You might want to log the error or handle it, 
        # but for dashboard load, we usually just want it to render.
        # If critical errors persist, the error page logic from previous steps handles specific actions.

    context = {
        'state': state,
        'candidates': state.get('candidates', [])
    }
    return render(request, 'hiring_app/dashboard.html', context)

def generate_jd(request):
    if request.method == "POST":
        role = request.POST.get('role')
        experience = request.POST.get('experience') # Capture experience input
        
        automator = get_automator()
        
        # Pass both role and experience to the service
        jd = automator.generate_jd(role, experience)
        
        # Return context to dashboard so inputs stay filled
        context = {
            'jd_preview': jd, 
            'role_preview': role,
            'exp_preview': experience 
        }
        
        # We need to reload the state for the rest of the dashboard
        state = automator.load_state()
        context['state'] = state
        context['candidates'] = state.get('candidates', [])
        
        return render(request, 'hiring_app/dashboard.html', context)
    return redirect('dashboard')

def create_campaign(request):
    if request.method == "POST":
        role = request.POST.get('role')
        jd = request.POST.get('jd_text')
        
        # LinkedIn Inputs
        linkedin_token = request.POST.get('linkedin_token')
        linkedin_urn = request.POST.get('linkedin_urn')
        
        automator = get_automator()
        # Pass all args to the service
        form_url, sheet_url = automator.create_campaign(role, jd, linkedin_token, linkedin_urn)
        
        return redirect('dashboard')
    return redirect('dashboard')

def sync_responses(request):
    automator = get_automator()
    automator.sync_responses()
    return redirect('dashboard')

def send_invites(request):
    if request.method == "POST":
        # Get emails from checkbox in UI
        selected_emails = request.POST.getlist('selected_candidates')
        interview_date = request.POST.get('interview_date') # Format YYYY-MM-DDTHH:MM
        
        print(f"DEBUG: Attempting to send to: {selected_emails}")
        
        if not selected_emails:
            print("DEBUG: No emails were selected!")
            return redirect('dashboard')
        
        automator = get_automator()
        results = automator.send_invites(selected_emails, "Hiring Team", interview_date)
        
        # Optional: Print results to console for debugging
        print("\n--------- EMAIL RESULTS ---------")
        for r in results:
            print(r)
        print("---------------------------------\n")
        
    return redirect('dashboard')

def send_outcomes(request):
    if request.method == "POST":
        # Get list of people selected for HIRE
        hired_emails = request.POST.getlist('hired_candidates')
        
        automator = get_automator()
        results = automator.send_outcomes(hired_emails)
        
        print("\n--------- OUTCOME RESULTS ---------")
        for r in results:
            print(r)
        print("-----------------------------------\n")
        
    return redirect('dashboard')