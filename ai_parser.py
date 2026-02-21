
import os
import json
import google.generativeai as genai
from datetime import datetime

try:
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
except Exception as e:
    print(f"Error configuring Google AI: {e}")


def get_working_model_name():
    try:
        available = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available.append(m.name)
        
        preferences = ["models/gemini-1.5-flash", "models/gemini-1.5-pro", "models/gemini-1.0-pro", "models/gemini-pro"]
        for pref in preferences:
            if pref in available: return pref
        if available: return available[0]
    except:
        pass
    return 'models/gemini-1.5-flash'

model_name = get_working_model_name()
print(f"--- AI Parser using Model: {model_name} ---")

generation_config = {
  "temperature": 0.1,
  "top_p": 0.95,
  "top_k": 64,
  "max_output_tokens": 2048,
}

model = genai.GenerativeModel(
    model_name=model_name,
    generation_config=generation_config
)

def parse_email_with_gemini(email_content: str) -> dict | None:
    """
    Uses Google Gemini to parse email content and extract interview details.
    """

    prompt = f"""
    You are an expert system that extracts interview details from emails.
    Analyze the following email content and return a JSON object with these exact keys:
    "companyName", "role", "interviewDateUTC", "interviewType".
    
    Rules:
    - The interviewType must be one of: 'Behavioral', 'Technical', 'Case', 'Screening', 'Unknown'.
    - The interviewDateUTC must be in ISO 8601 format (YYYY-MM-DDTHH:MM:SSZ). Convert to UTC if a timezone is found.
    - If a value is not found, set it to null.
    - RETURN ONLY PURE JSON. NO MARKDOWN.
    
    Email Content:
    ---
    {email_content}
    ---
    """

    try:
        response = model.generate_content(prompt)
        

        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
            
        parsed_json = json.loads(text)

        if not all(k in parsed_json for k in ["companyName", "role", "interviewDateUTC"]):
            print("AI response missing required keys.")
            return None

        if parsed_json["interviewDateUTC"]:
             datetime.fromisoformat(parsed_json["interviewDateUTC"].replace("Z", "+00:00"))

        return parsed_json

    except Exception as e:
        print(f"Error parsing email with Google Gemini: {e}")
        return None
