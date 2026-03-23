from fastapi import Header, HTTPException
from firebase_admin import auth

async def verify_token(authorization: str = Header(...)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid/Missing authorization header")
    
    token = authorization.split("Bearer ")[1]
    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except Exception as e:
        print(f"Token error: {e}")
        raise HTTPException(status_code=401, detail="Invalid token")
