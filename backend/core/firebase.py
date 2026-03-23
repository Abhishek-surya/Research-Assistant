import firebase_admin
from firebase_admin import credentials
import os

def init_firebase():
    if not firebase_admin._apps:
        # Load the service account key that we copied from your downloads
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cert_path = os.path.join(base_dir, 'serviceAccountKey.json')
        
        cred = credentials.Certificate(cert_path)
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'abhishek-rag-2026.appspot.com'
        })
