
from dotenv import load_dotenv
load_dotenv() 

import os
import json
import random
from fastapi import FastAPI, Request, Depends, BackgroundTasks
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth
from sqlmodel import Session, select
from pydantic import BaseModel
from fastapi import FastAPI, Depends, Request, HTTPException
import google.generativeai as genai

from database import User, get_session, create_db_and_tables, encrypt_data
from gmail_service import start_email_sync


try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("!!! WARNING: GOOGLE_API_KEY not found in .env !!!")
    genai.configure(api_key=api_key)
    print("--- Gemini Configured ---")
except Exception as e:
    print(f"Error configuring Google AI in main.py: {e}")

def get_working_model_name():
    """
    Dynamically finds a working model name to avoid 404 errors.
    """
    try:
        print("--- Checking available Gemini models... ---")
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        print(f"Found models: {available_models}")


        preferences = [
            "models/gemini-1.5-flash",
            "models/gemini-1.5-pro",
            "models/gemini-1.0-pro",
            "models/gemini-pro"
        ]


        for pref in preferences:
            if pref in available_models:
                return pref
        

        for m in available_models:
            if 'flash' in m: return m
        for m in available_models:
            if 'pro' in m: return m
            

        if available_models:
            return available_models[0]
            
    except Exception as e:
        print(f"Error listing models: {e}")
    

    return 'models/gemini-1.5-flash'

model_name = get_working_model_name()
print(f"--- SELECTED MODEL: {model_name} ---")
feedback_model = genai.GenerativeModel(model_name)



app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000","https://neural-nexus-frontend-fl2o.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY"))

oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile https://www.googleapis.com/auth/gmail.readonly'}
)

@app.on_event("startup")
def on_startup():
    create_db_and_tables()

@app.get("/auth/google/login")
async def login_via_google(request: Request):
    redirect_uri = 'https://neural-nexus-backend-4qh8.onrender.com/auth/google/callback'
    return await oauth.google.authorize_redirect(request, redirect_uri)

@app.get("/auth/google/callback")
async def auth_via_google(request: Request, db: Session = Depends(get_session)):
    token = await oauth.google.authorize_access_token(request)
    user_info = token.get('userinfo')
    if user_info:
        email = user_info['email']
        db_user = db.exec(select(User).where(User.email == email)).first()
        encrypted_access = encrypt_data(token['access_token'])
        if db_user:
            db_user.encrypted_access_token = encrypted_access
            if token.get('refresh_token'):
                db_user.encrypted_refresh_token = encrypt_data(token['refresh_token'])
        else:
            db_user = User(
                email=email,
                encrypted_access_token=encrypted_access,
                encrypted_refresh_token=encrypt_data(token['refresh_token']) if token.get('refresh_token') else None
            )
        db.add(db_user)
        db.commit()
        request.session['user'] = dict(user_info)
    return RedirectResponse(url='https://neural-nexus-frontend-fl2o.vercel.app/dashboard')

@app.post("/sync-emails")
async def sync_emails(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_session)):
    user_info = request.session.get('user')
    if not user_info: return {"error": "User not authenticated"}, 401
    background_tasks.add_task(start_email_sync, user_info['email'], db)
    return {"message": "Syncing with email server..."}

@app.get("/interviews")
async def get_interviews(request: Request, db: Session = Depends(get_session)):
    user_info = request.session.get('user')
    if not user_info: raise HTTPException(status_code=401, detail="User not authenticated")
    user = db.exec(select(User).where(User.email == user_info['email'])).first()
    return user.interviews if user else []


class AnswerAnalysisRequest(BaseModel):
    question: str
    answer: str

@app.post("/interviews/analyze-answer")
async def analyze_answer(request: AnswerAnalysisRequest):
    print(f"\n--- 1. Endpoint Hit: analyze_answer ---")
    
    prompt = f"""
    As an expert interview coach, analyze the following user's answer to a specific interview question.

    The interview question was:
    "{request.question}"

    The user's spoken answer was:
    "{request.answer}"

    Provide concise, constructive feedback in three specific areas:
    1.  **Clarity and Structure:** Was the answer clear and well-structured?
    2.  **Content and Relevance:** Did the answer directly address the question?
    3.  **Delivery and Confidence:** Identify potential filler words or lack of confidence.
    You must provide your feedback in exactly one single paragraph of no more than 100 words.
    Format your response in Markdown.
    
    """

    try:
        print(f"--- 2. Sending Prompt to Gemini using {model_name} ---") 
        response = feedback_model.generate_content(prompt) 
        
        print("--- 3. Received Response from Gemini ---")
        feedback = response.text
        return {"feedback": feedback}
    except Exception as e:
        print(f"!!! ERROR in analyze_answer: {e}") 
        return {"error": f"Failed to get AI feedback: {e}"}, 500
