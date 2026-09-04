"""app/identity/jwt.py — token verification. Private: only app/identity/__init__.py imports this.

Two verification paths (ticket 03-1, appendix A):
1. RS256/ES256 via Supabase's JWKS endpoint (`SUPABASE_URL/auth/v1/.well-known/jwks.json`),
   fetched via `jwt.PyJWKClient` with a 10-minute cache (`lifespan=600`; `cache_keys=True` is
   required or PyJWKClient never actually caches — see PyJWT 2.13.0 source, default False).
2. HS256 via the Supabase project's legacy shared secret (`SUPABASE_JWT_SECRET`), **only**
   when `IDENTITY_ALLOW_HS256=1` — local dev only, lets tests mint tokens without a real
   signup. `supabase start` prints this secret under `JWT_SECRET` in `supabase status`.

Both paths verify `exp` and `aud="authenticated"` (Supabase's fixed audience for signed-in
users — see GoTrue docs) via `jwt.decode`'s own checks; algorithm confusion is blocked by
reading `alg` from the token header first and only accepting it if it is in the allow-list
below (never trust the caller to pick HS256 against an RS256/ES256-configured project).
"""

import jwt
from jwt import PyJWKClient

from app.core.config import settings

_ALLOWED_ALGORITHMS = ("RS256", "ES256", "HS256")
_AUDIENCE = "authenticated"
_JWKS_CACHE_SECONDS = 600  # 10 分鐘（票 03-1 §「JWKS client with 10-min cache」）

_jwks_client: PyJWKClient | None = None


def _jwks_url() -> str:
    base = settings().supabase_url.rstrip("/")
    return f"{base}/auth/v1/.well-known/jwks.json"


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(
            _jwks_url(), cache_keys=True, lifespan=_JWKS_CACHE_SECONDS
        )
    return _jwks_client


def decode(token: str) -> dict:
    """Verify signature + exp + aud, return claims. Raises jwt.PyJWTError (or a subclass) on
    any failure — callers (app.identity.authenticate) treat all of them as 401."""
    header = jwt.get_unverified_header(token)
    alg = header.get("alg")
    if alg not in _ALLOWED_ALGORITHMS:
        raise jwt.InvalidAlgorithmError(f"unsupported alg: {alg}")

    if alg == "HS256":
        if not settings().identity_allow_hs256:
            raise jwt.InvalidAlgorithmError(
                "HS256 disabled (set IDENTITY_ALLOW_HS256=1 for local dev)"
            )
        secret = settings().supabase_jwt_secret
        if not secret:
            raise jwt.InvalidKeyError("SUPABASE_JWT_SECRET not set")
        return jwt.decode(token, secret, algorithms=["HS256"], audience=_AUDIENCE)

    signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
    return jwt.decode(token, signing_key.key, algorithms=[alg], audience=_AUDIENCE)
