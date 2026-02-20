"""
Authentication utilities for Supabase JWT verification.

The frontend uses supabase.auth.signInWithPassword() and sends the JWT
in the Authorization header. This module verifies the JWT and extracts user info.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from typing import Optional
import requests
from app.core.config import settings

# Security scheme for Bearer token
security = HTTPBearer()


class User:
    """User model extracted from JWT token."""
    def __init__(self, user_id: str, email: str, role: Optional[str] = None):
        self.id = user_id
        self.email = email
        self.role = role or "user"  # Default role


# Cache for JWKS keys (to avoid fetching on every request)
_jwks_cache = None


def get_supabase_jwks():
    """
    Fetch Supabase's JSON Web Key Set (JWKS) for JWT verification.
    
    Supabase uses RS256 (asymmetric) signing, so we need their public key
    to verify tokens. The JWKS endpoint provides this public key.
    
    Returns:
        dict: JWKS containing public keys for token verification
    """
    global _jwks_cache
    
    # Return cached JWKS if available
    if _jwks_cache is not None:
        return _jwks_cache
    
    try:
        # Fetch JWKS from Supabase (correct endpoint with .well-known path)
        jwks_url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
        response = requests.get(jwks_url, timeout=10)
        response.raise_for_status()
        _jwks_cache = response.json()
        return _jwks_cache
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch JWKS from Supabase: {str(e)}",
        )


def verify_token(token: str) -> dict:
    """
    Verify Supabase JWT token and return decoded payload.
    
    Supabase signs JWTs using asymmetric encryption (ES256 or RS256) with their private key.
    We verify them using their public key from the JWKS endpoint.
    
    Args:
        token: JWT token from Authorization header
        
    Returns:
        Decoded JWT payload containing user info
        
    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        # Fetch JWKS (contains public keys for verification)
        jwks = get_supabase_jwks()
        
        # Decode and verify JWT using multiple supported algorithms
        # python-jose automatically matches the key from JWKS based on the token's 'kid' header
        # Supabase uses ES256 (ECC P-256) for newer projects and RS256 for older ones
        payload = jwt.decode(
            token,
            jwks,
            algorithms=["ES256", "RS256"],  # Support both elliptic curve and RSA
            audience="authenticated",  # Supabase uses "authenticated" as audience
            options={"verify_aud": True}
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> User:
    """
    FastAPI dependency to get current authenticated user from JWT token.
    
    Usage in route:
        @app.get("/protected")
        def protected_route(current_user: User = Depends(get_current_user)):
            return {"user_id": current_user.id, "email": current_user.email}
    
    Args:
        credentials: HTTP Bearer token from Authorization header
        
    Returns:
        User object with id, email, and role
        
    Raises:
        HTTPException: If token is missing, invalid, or expired
    """
    token = credentials.credentials
    payload = verify_token(token)
    
    # Extract user info from JWT payload
    # Supabase JWT structure: {"sub": "user_id", "email": "user@example.com", ...}
    user_id = payload.get("sub")
    email = payload.get("email")
    role = payload.get("role")  # You can add custom claims in Supabase
    
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate user",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return User(user_id=user_id, email=email, role=role)


def require_role(required_role: str):
    """
    Dependency factory for role-based access control (future use).
    
    Usage:
        @app.delete("/properties/{id}")
        def delete_property(
            id: int,
            current_user: User = Depends(require_role("admin"))
        ):
            # Only admins can delete
            ...
    
    Args:
        required_role: Role required to access the route (e.g., "admin", "manager")
        
    Returns:
        Dependency function that checks user role
    """
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {required_role}",
            )
        return current_user
    return role_checker
