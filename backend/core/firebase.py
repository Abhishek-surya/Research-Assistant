import firebase_admin
from firebase_admin import credentials
import os
import json

def init_firebase():
    if not firebase_admin._apps:
        # Check for service account JSON in environment variable (for Render/Production)
        service_account_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON')
        
        if service_account_json:
            # Initialize using the environment variable
            service_account_info = json.loads(service_account_json)
            cred = credentials.Certificate(service_account_info)
        else:
            # Fallback to local file (for Local Development)
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cert_path = os.path.join(base_dir, 'serviceAccountKey.json')
            
            if os.path.exists(cert_path):
                cred = credentials.Certificate(cert_path)
            else:
                raise FileNotFoundError(f"Service account key not found at {cert_path} and FIREBASE_SERVICE_ACCOUNT_JSON is not set.")

        project_id = os.environ.get('FIREBASE_PROJECT_ID', 'ai-research-assistant-3d978')
        firebase_admin.initialize_app(cred, {
            'projectId': project_id
        })
