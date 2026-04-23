import firebase_admin
from firebase_admin import credentials
import os
import json

def init_firebase():
    if not firebase_admin._apps:
        # 1. Attempt to initialize using individual Env Vars (Safest for Render)
        private_key = os.environ.get('FIREBASE_PRIVATE_KEY')
        client_email = os.environ.get('FIREBASE_CLIENT_EMAIL')
        project_id = os.environ.get('FIREBASE_PROJECT_ID', 'ai-research-assistant-3d978')

        if private_key and client_email:
            # Fix newline formatting which often breaks on Render/Linux envs
            processed_key = private_key.replace('\\n', '\n')
            cred = credentials.Certificate({
                "type": "service_account",
                "project_id": project_id,
                "private_key": processed_key,
                "client_email": client_email,
                "token_uri": "https://oauth2.googleapis.com/token",
            })
            print(f"[FIREBASE] Initialized using individual environment variables for project: {project_id}")
        
        # 2. Fallback to full JSON string
        elif os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON'):
            service_account_info = json.loads(os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON'))
            cred = credentials.Certificate(service_account_info)
            print(f"[FIREBASE] Initialized using JSON string.")

        # 3. Fallback to local file (Development)
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cert_path = os.path.join(base_dir, 'serviceAccountKey.json')
            if os.path.exists(cert_path):
                cred = credentials.Certificate(cert_path)
                print(f"[FIREBASE] Initialized using local serviceAccountKey.json")
            else:
                raise FileNotFoundError("No Firebase credentials found (checked Env Vars and local file).")

        firebase_admin.initialize_app(cred, {
            'projectId': project_id
        })
