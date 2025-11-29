import google.generativeai as genai
import os

# 1. SETUP: We'll try to load the key from your settings, or paste it here directly
try:
    from my_hiring_project.settings import GEMINI_API_KEY
    api_key = GEMINI_API_KEY
except:
    api_key = "PASTE_YOUR_API_KEY_HERE_IF_SETTINGS_FAIL"

print(f"Checking models for API Key: {api_key[:10]}...")

genai.configure(api_key=api_key)

try:
    print("\n✅ Available Models for generateContent:")
    found = False
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"  - {m.name}")
            found = True
    
    if not found:
        print("  (No models found. Check if the API Key has the right permissions)")
        
except Exception as e:
    print(f"\n❌ Error listing models: {e}")
