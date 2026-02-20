# Authentication System Documentation

## Table of Contents
1. [Problem Overview](#problem-overview)
2. [The Solution](#the-solution)
3. [How Authentication Works (Complete Flow)](#how-authentication-works-complete-flow)
4. [Technical Deep Dive](#technical-deep-dive)
5. [Code Implementation](#code-implementation)
6. [Testing & Verification](#testing--verification)

---

## Problem Overview

### What Was Wrong?

The backend was rejecting all authenticated requests with a `401 Unauthorized` error:

```
"Invalid authentication credentials: The specified alg value is not allowed"
```

### Root Cause

**JWT Algorithm Mismatch**: The backend was configured to verify JWT tokens using the **RS256** algorithm (RSA asymmetric encryption), but Supabase was actually signing tokens using the **ES256** algorithm (Elliptic Curve Digital Signature Algorithm with P-256 curve).

#### Why This Happened

When Supabase creates a new project, it generates a signing key for JWT tokens. Older projects used RS256 (RSA-based), but newer projects use ES256 (Elliptic Curve-based) because:
- **ES256 is more efficient**: Smaller key sizes with equivalent security
- **Faster operations**: Quicker signing and verification
- **Modern standard**: Industry is moving toward elliptic curve cryptography

Our Supabase dashboard showed:
```
Current key: ECC (P-256)
```

This indicated ES256, but our backend code only supported RS256.

---

## The Solution

### What Was Fixed

Updated the JWT verification function in `/app/core/auth.py` to accept **both ES256 and RS256** algorithms:

**Before:**
```python
payload = jwt.decode(
    token,
    jwks,
    algorithms=["RS256"],  # ❌ Only RSA
    audience="authenticated",
    options={"verify_aud": True}
)
```

**After:**
```python
payload = jwt.decode(
    token,
    jwks,
    algorithms=["ES256", "RS256"],  # ✅ Both Elliptic Curve and RSA
    audience="authenticated",
    options={"verify_aud": True}
)
```

This makes our backend **compatible with both old and new Supabase projects**.

---

## How Authentication Works (Complete Flow)

### Overview

Our authentication system uses **JWT (JSON Web Tokens)** with **asymmetric cryptography**. Here's the complete flow from login to API access:

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐         ┌──────────────┐
│   Frontend  │────1───▶│   Supabase   │────2───▶│   Frontend  │────3───▶│   Backend    │
│   (React)   │         │     Auth     │         │             │         │   (FastAPI)  │
└─────────────┘         └──────────────┘         └─────────────┘         └──────────────┘
                                                                                  │
                                                                                  │ 4
                                                                                  ▼
                                                                         ┌──────────────┐
                                                                         │   Supabase   │
                                                                         │     JWKS     │
                                                                         └──────────────┘
```

### Step-by-Step Flow

#### **Step 1: User Logs In (Frontend → Supabase)**

When a user logs in, the frontend calls Supabase:

```typescript
// Frontend code
const { data, error } = await supabase.auth.signInWithPassword({
  email: 'user@example.com',
  password: 'password123'
})
```

#### **Step 2: Supabase Issues JWT Token (Supabase → Frontend)**

If credentials are valid, Supabase:
1. **Creates a JWT token** signed with their **private key** (ES256)
2. **Returns the token** to the frontend along with user data

The JWT token contains:
- **Header**: Algorithm info (`alg: "ES256"`) and key ID (`kid`)
- **Payload**: User data (`sub`, `email`, `role`, expiration time)
- **Signature**: Cryptographic signature created with Supabase's private ES256 key

Example JWT structure:
```json
{
  "header": {
    "alg": "ES256",
    "kid": "unique-key-id",
    "typ": "JWT"
  },
  "payload": {
    "sub": "user-uuid-here",
    "email": "user@example.com",
    "role": "authenticated",
    "aud": "authenticated",
    "exp": 1739756543,
    "iat": 1739752943
  },
  "signature": "..." // Signed with Supabase's private key
}
```

#### **Step 3: Frontend Sends Token to Backend (Frontend → Backend)**

For every API request, the frontend includes the token in the `Authorization` header:

```typescript
// Frontend code (from api.ts)
const { data: { session } } = await supabase.auth.getSession()

const response = await fetch('http://localhost:8000/tickets', {
  headers: {
    'Authorization': `Bearer ${session.access_token}`
  }
})
```

#### **Step 4: Backend Verifies Token (Backend → Supabase JWKS → User)**

When the backend receives a request:

1. **Extracts the token** from the `Authorization: Bearer <token>` header
2. **Fetches Supabase's public keys** from the JWKS endpoint (cached for performance)
3. **Verifies the token signature** using the public key
4. **Decodes the payload** to get user information
5. **Allows or denies access** based on verification result

---

## Technical Deep Dive

### What is JWT (JSON Web Token)?

A JWT is a self-contained token that securely transmits information between parties. It consists of three parts:

```
header.payload.signature
eyJhbGc...  .  eyJzdWI...  .  SflKxwRJ...
```

- **Header**: Token metadata (algorithm, type)
- **Payload**: User data (claims)
- **Signature**: Cryptographic proof of authenticity

### Asymmetric vs Symmetric Encryption

#### **Symmetric (HS256) - NOT USED**
- Same key for signing AND verifying
- ❌ Insecure for distributed systems
- ❌ Every service needs the secret key
- ❌ If compromised, anyone can create fake tokens

#### **Asymmetric (ES256, RS256) - USED ✅**
- **Private key**: Only Supabase has this (signs tokens)
- **Public key**: Everyone can access this (verifies tokens)
- ✅ More secure: Private key never leaves Supabase
- ✅ Backend can verify without knowing private key
- ✅ If public key is compromised, no one can forge tokens

### JWT Signing Algorithms

| Algorithm | Type | Key Size | Speed | Security | Use Case |
|-----------|------|----------|-------|----------|----------|
| **HS256** | Symmetric | 256 bits | Fast | ⚠️ Moderate | Single app |
| **RS256** | Asymmetric (RSA) | 2048+ bits | Slower | ✅ High | Legacy systems |
| **ES256** | Asymmetric (ECC) | 256 bits | Fast | ✅ High | Modern systems |

**Why ES256 is Better:**
- Same security as RS256 with much smaller keys
- Faster signing and verification
- Less bandwidth (smaller tokens)
- Modern cryptographic standard

### What is JWKS (JSON Web Key Set)?

JWKS is a public endpoint that provides the **public keys** needed to verify JWT signatures.

**Supabase JWKS URL:**
```
https://fjrylvonlwpndrrfwyif.supabase.co/auth/v1/.well-known/jwks.json
```

**Example JWKS Response:**
```json
{
  "keys": [
    {
      "kty": "EC",           // Key type: Elliptic Curve
      "crv": "P-256",        // Curve: P-256 (for ES256)
      "kid": "key-id-123",   // Key ID (matches JWT header)
      "x": "...",            // Public key x coordinate
      "y": "...",            // Public key y coordinate
      "alg": "ES256",        // Algorithm
      "use": "sig"           // Usage: signature verification
    }
  ]
}
```

### How Token Verification Works

```python
# Step 1: Fetch JWKS (public keys)
jwks = requests.get('https://your-project.supabase.co/auth/v1/.well-known/jwks.json')

# Step 2: Decode token (python-jose automatically matches key by 'kid')
payload = jwt.decode(
    token,
    jwks,
    algorithms=["ES256", "RS256"],  # Accept both algorithms
    audience="authenticated",        # Verify token audience
    options={"verify_aud": True}     # Enable audience verification
)

# Step 3: Extract user info from payload
user_id = payload["sub"]       # User UUID
email = payload["email"]       # User email
role = payload["role"]         # User role (if set)
```

**Security Checks Performed:**
1. ✅ **Signature verification**: Ensures token was signed by Supabase
2. ✅ **Expiration check**: Rejects expired tokens
3. ✅ **Audience verification**: Ensures token is for our backend
4. ✅ **Algorithm verification**: Only accepts ES256 or RS256
5. ✅ **Key matching**: Uses correct public key based on `kid` header

---

## Code Implementation

### File Structure

```
app/
├── core/
│   ├── auth.py        # 🔐 Authentication logic (JWT verification)
│   └── config.py      # ⚙️ Configuration settings
├── api/
│   └── routes/
│       ├── tickets.py    # Protected with auth
│       ├── properties.py # Protected with auth
│       └── ...          # All other routes
└── main.py            # FastAPI app with CORS
```

### 1. Configuration (`app/core/config.py`)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    ENV: str = "dev"
    
    # Supabase Authentication
    SUPABASE_URL: str              # e.g., https://xyz.supabase.co
    SUPABASE_JWT_SECRET: str       # Not used for ES256, kept for compatibility
    
    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()
```

**Environment Variables (`.env`):**
```env
SUPABASE_URL=https://fjrylvonlwpndrrfwyif.supabase.co
SUPABASE_JWT_SECRET=wKJpkz... # Base64 secret (for reference only)
```

### 2. Authentication Module (`app/core/auth.py`)

#### **User Model**
```python
class User:
    """User model extracted from JWT token."""
    def __init__(self, user_id: str, email: str, role: Optional[str] = None):
        self.id = user_id          # Supabase user UUID
        self.email = email         # User email
        self.role = role or "user" # User role (default: "user")
```

#### **JWKS Fetching (with caching)**
```python
_jwks_cache = None  # Global cache to avoid repeated requests

def get_supabase_jwks():
    """
    Fetch Supabase's JSON Web Key Set (JWKS) for JWT verification.
    
    Why JWKS?
    - Supabase uses asymmetric encryption (ES256/RS256)
    - We need their PUBLIC KEY to verify tokens
    - JWKS endpoint provides this public key
    - Cached to avoid fetching on every request
    """
    global _jwks_cache
    
    if _jwks_cache is not None:
        return _jwks_cache  # Return cached keys
    
    try:
        jwks_url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        response = requests.get(jwks_url, timeout=10)
        response.raise_for_status()
        _jwks_cache = response.json()
        return _jwks_cache
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch JWKS from Supabase: {str(e)}"
        )
```

#### **Token Verification (THE FIX)**
```python
def verify_token(token: str) -> dict:
    """
    Verify Supabase JWT token and return decoded payload.
    
    Process:
    1. Fetch JWKS (Supabase's public keys)
    2. Decode token using python-jose
    3. python-jose automatically:
       - Matches key from JWKS using 'kid' header
       - Verifies signature with public key
       - Checks expiration time
       - Validates audience
    4. Return user data from token payload
    """
    try:
        jwks = get_supabase_jwks()
        
        # 🔧 THE FIX: Support both ES256 and RS256
        payload = jwt.decode(
            token,
            jwks,
            algorithms=["ES256", "RS256"],  # ✅ Both algorithms supported
            audience="authenticated",
            options={"verify_aud": True}
        )
        return payload
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except JWTError as e:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid authentication credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"}
        )
```

#### **FastAPI Dependency**
```python
security = HTTPBearer()  # Extracts Bearer token from Authorization header

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    """
    FastAPI dependency to get current authenticated user.
    
    Usage in routes:
        @app.get("/tickets")
        def get_tickets(current_user: User = Depends(get_current_user)):
            # Only authenticated users can access this
            return {"user_id": current_user.id}
    """
    token = credentials.credentials  # Extract token from "Bearer <token>"
    payload = verify_token(token)    # Verify and decode token
    
    # Extract user data from JWT payload
    user_id = payload.get("sub")     # Supabase uses "sub" for user ID
    email = payload.get("email")
    role = payload.get("role")
    
    if not user_id:
        raise HTTPException(status_code=401, detail="Could not validate user")
    
    return User(user_id=user_id, email=email, role=role)
```

### 3. Protecting Routes

#### **Before (Unprotected)**
```python
@router.get("/tickets")
def get_tickets(db: Session = Depends(get_db)):
    # ❌ Anyone can access
    return db.query(Ticket).all()
```

#### **After (Protected)**
```python
from app.core.auth import get_current_user, User

@router.get("/tickets")
def get_tickets(
    current_user: User = Depends(get_current_user),  # ✅ Requires authentication
    db: Session = Depends(get_db)
):
    # Only authenticated users can access
    # current_user.id, current_user.email available
    return db.query(Ticket).all()
```

### 4. CORS Configuration (`app/main.py`)

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "https://automated-dashboard-frontend.vercel.app"  # Production frontend
    ],
    allow_credentials=True,  # Allow cookies and Authorization headers
    allow_methods=["*"],     # Allow all HTTP methods
    allow_headers=["*"],     # Allow all headers
)
```

---

## Testing & Verification

### Manual Testing

1. **Login via Frontend:**
   ```
   https://automated-dashboard-frontend.vercel.app/login
   ```

2. **Check Browser Console:**
   ```javascript
   // Should see successful requests
   GET http://localhost:8000/tickets/ 200 OK
   ```

3. **Check Backend Logs:**
   ```
   INFO: 127.0.0.1:49379 - "GET /tickets HTTP/1.1" 200 OK
   ```

### Testing with cURL

```bash
# 1. Get a token from Supabase (after login)
TOKEN="eyJhbGc..."

# 2. Test protected endpoint
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/tickets/

# Expected: 200 OK with ticket data
# If token invalid: 401 Unauthorized
```

### Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| `401 - alg not allowed` | Algorithm mismatch | ✅ Fixed: Support ES256 + RS256 |
| `401 - Token expired` | Token older than 1 hour | Re-login to get new token |
| `401 - Invalid credentials` | Malformed/tampered token | Check token is sent correctly |
| `500 - Failed to fetch JWKS` | Network issue / wrong URL | Verify SUPABASE_URL in .env |
| CORS error | Frontend URL not whitelisted | Add URL to CORS allow_origins |

---

## Security Best Practices

### ✅ What We Do Right

1. **Asymmetric encryption**: Private key never leaves Supabase
2. **Token expiration**: Tokens expire after 1 hour
3. **HTTPS only**: All production traffic over SSL
4. **JWKS caching**: Reduces attack surface
5. **Audience verification**: Ensures tokens are for our backend
6. **Algorithm whitelist**: Only ES256 and RS256 allowed

### ⚠️ Important Security Notes

1. **Never log tokens**: Tokens are sensitive credentials
2. **Use HTTPS in production**: HTTP exposes tokens to interception
3. **Short token lifetime**: 1-hour expiration limits damage from stolen tokens
4. **Refresh tokens**: Use refresh tokens for long-lived sessions
5. **Environment variables**: Keep secrets in `.env`, never commit to git

### Environment Variables Checklist

```env
# Required for authentication
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_JWT_SECRET=your-jwt-secret-here

# Database
DATABASE_URL=postgresql://...

# Environment
ENV=dev  # or 'prod'
```

---

## Deployment Checklist

### Heroku Deployment

1. **Set environment variables:**
   ```bash
   heroku config:set SUPABASE_URL=https://xyz.supabase.co
   heroku config:set SUPABASE_JWT_SECRET=your-secret
   ```

2. **Verify requirements.txt:**
   ```txt
   python-jose[cryptography]==3.3.0
   requests==2.32.3
   ```

3. **Deploy:**
   ```bash
   git push heroku main
   ```

4. **Test:**
   ```bash
   curl -H "Authorization: Bearer $TOKEN" https://your-app.herokuapp.com/tickets/
   ```

---

## Summary

### What Was Wrong
- Backend only supported RS256 algorithm
- Supabase was using ES256 algorithm
- Algorithm mismatch caused `401 Unauthorized` errors

### What Was Fixed
- Updated `jwt.decode()` to accept both ES256 and RS256
- Now compatible with all Supabase projects (old and new)

### How It Works
1. User logs in via Supabase (frontend)
2. Supabase signs JWT with ES256 private key
3. Frontend sends token to backend in Authorization header
4. Backend fetches Supabase's ES256 public key from JWKS
5. Backend verifies token signature with public key
6. Backend extracts user info and allows access

### Key Technologies
- **JWT**: Self-contained authentication tokens
- **ES256**: Elliptic curve cryptography for signing
- **JWKS**: Public endpoint for verification keys
- **FastAPI Dependencies**: Automatic auth injection
- **python-jose**: JWT library with ES256 support

---

## Additional Resources

- [JWT.io](https://jwt.io/) - JWT debugger and documentation
- [Supabase Auth Docs](https://supabase.com/docs/guides/auth) - Official Supabase authentication guide
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/) - FastAPI security patterns
- [RFC 7519](https://tools.ietf.org/html/rfc7519) - JWT specification
- [RFC 7518](https://tools.ietf.org/html/rfc7518) - JSON Web Algorithms (JWA)

---

**Document Version:** 1.0  
**Last Updated:** February 17, 2026  
**Author:** Development Team  
**Status:** ✅ Authentication Working
