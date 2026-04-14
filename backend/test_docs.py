import sys, os
import asyncio

from api.routes.documents import list_documents
from google.cloud import firestore
try:
    import firebase_admin
    from firebase_admin import credentials
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
except Exception:
    pass

async def main():
    try:
        user_token = {"email": "abhisheksuryavanshi220@gmail.com"}
        result = await list_documents(user_token)
        print("Success:")
        print(result)
    except Exception as e:
        print("Error:")
        import traceback
        traceback.print_exc()

asyncio.run(main())
