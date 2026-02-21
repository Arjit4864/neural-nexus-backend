import httpx
import base64
from sqlmodel import Session, select
from datetime import datetime

from database import User, Interview, decrypt_data
from ai_parser import parse_email_with_gemini

GMAIL_API_BASE_URL = "https://www.googleapis.com/gmail/v1/users/me"

def start_email_sync(user_email: str, db: Session):
    """
    Fetches and processes emails for a given user.
    """
    print(f"Starting email sync for {user_email}...")
    statement = select(User).where(User.email == user_email)
    user = db.exec(statement).first()

    if not user:
        print(f"User {user_email} not found in DB.")
        return

    access_token = decrypt_data(user.encrypted_access_token)
    headers = {"Authorization": f"Bearer {access_token}"}
    
    search_query = "subject:(interview) newer_than:14d"
    params = {"q": search_query, "maxResults": 5}
    
    try:
        with httpx.Client() as client:
            response = client.get(f"{GMAIL_API_BASE_URL}/messages", headers=headers, params=params)
            
            if response.status_code == 401:
                print(f"Access token expired for {user_email}.")
                return

            response.raise_for_status()
            messages = response.json().get("messages", [])

            if not messages:
                print("No new interview emails found.")
                return

            for message_info in messages:
                msg_id = message_info['id']
                msg_response = client.get(f"{GMAIL_API_BASE_URL}/messages/{msg_id}", headers=headers, params={"format": "full"})
                msg_data = msg_response.json()
                
                payload = msg_data.get('payload', {})
                body_data = None
                
                if 'parts' in payload:
                    for part in payload['parts']:
                        if part['mimeType'] == 'text/plain' and 'data' in part['body']:
                            body_data = part['body']['data']
                            break
                else:
                    body_data = payload.get('body', {}).get('data')

                if body_data:
                    email_body = base64.urlsafe_b64decode(body_data).decode('utf-8')
                    
                    parsed_data = parse_email_with_gemini(email_body)
                    
                    if parsed_data and parsed_data.get('companyName'):
                        print(f"AI successfully parsed an interview: {parsed_data['companyName']}")
                        
                        existing = db.exec(select(Interview).where(
                            Interview.user_id == user.id,
                            Interview.company_name == parsed_data['companyName'],
                            Interview.role_title == parsed_data['role']
                        )).first()
                        
                        if not existing:
                            new_interview = Interview(
                                company_name=parsed_data['companyName'],
                                role_title=parsed_data['role'],
                                interview_date=datetime.fromisoformat(parsed_data["interviewDateUTC"].replace("Z", "+00:00")),
                                interview_type=parsed_data.get('interviewType', 'Unknown'),
                                user_id=user.id
                            )
                            db.add(new_interview)
                            db.commit()
                        else:
                            print("Interview already exists in DB.")

    except httpx.HTTPStatusError as e:
        print(f"Error communicating with Gmail API: {e}")
    except Exception as e:
        print(f"An unexpected error occurred during sync: {e}")
