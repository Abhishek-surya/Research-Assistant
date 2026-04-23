from fastapi import Header, HTTPException
from firebase_admin import auth

async def verify_token(authorization: str = Header(...)):
    if not authorization:
        print("[AUTH] 401: Missing authorization header")
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        print(f"[AUTH] 401: Invalid header format: {authorization[:20]}...")
        raise HTTPException(status_code=401, detail="Invalid authorization header format (Expected 'Bearer <token>')")
    
    token = parts[1]
    try:
        # Check standard Firebase token validity and matching Project ID
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except auth.ExpiredIdTokenError:
        print("[AUTH] 401: Token Expired")
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    except auth.InvalidIdTokenError:
        print("[AUTH] 401: Invalid Token Structure")
        raise HTTPException(status_code=401, detail="Invalid security token.")
    except Exception as e:
        # This will catch 'aud' (audience) mismatches specifically
        error_msg = str(e)
        print(f"[AUTH] 401: Verification failed: {error_msg}")
        raise HTTPException(status_code=401, detail=f"Authentication failed: {error_msg}")
