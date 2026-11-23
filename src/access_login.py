"""Owner login from anywhere, through Cloudflare Access.

Why: the app treats "no Cloudflare headers" as the owner, which is only safe while Streamlit listens on this
computer alone. To manage the app away from this computer, the owner opens a separate admin address
(e.g. pantun-admin.aimanjamal.com) that Cloudflare Access protects with an email one-time code.

After the login, Cloudflare adds a signed token (a JWT) to every request: header `Cf-Access-Jwt-Assertion`.
This module checks that token properly, so a visitor cannot fake it:
  1. the signature must come from one of our Cloudflare team's public keys (RS256),
  2. it must be issued by our team and meant for our admin application (the "AUD" tag),
  3. it must not be expired, and
  4. (optional) the email inside must be on the owner list.

Settings (in .env, never in git):
  PANTUN_ACCESS_TEAM    team name, e.g. "aiman" for aiman.cloudflareaccess.com
  PANTUN_ACCESS_AUD     the Application Audience (AUD) tag of the admin application
  PANTUN_OWNER_EMAILS   optional, comma-separated; if set, only these emails count as the owner
Without TEAM and AUD the feature is off and nothing changes.
"""

import base64
import json
import os
import time
import urllib.request

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

CERTS_TTL = 3600          # re-download Cloudflare's public keys at most once an hour (they rotate rarely)
_certs_cache = {"team": None, "at": 0.0, "keys": {}}


def settings():
    """(team, aud, owner emails) from the environment. team/aud are '' when the feature is off."""
    team = os.environ.get("PANTUN_ACCESS_TEAM", "").strip()
    aud = os.environ.get("PANTUN_ACCESS_AUD", "").strip()
    emails = {e.strip().lower() for e in os.environ.get("PANTUN_OWNER_EMAILS", "").split(",") if e.strip()}
    return team, aud, emails


def _b64url(part):
    """Decode one base64url piece of a JWT (padding is left off in JWTs)."""
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _rsa_key(jwk):
    """Public key object from a JSON Web Key (only the modulus n and exponent e are needed)."""
    n = int.from_bytes(_b64url(jwk["n"]), "big")
    e = int.from_bytes(_b64url(jwk["e"]), "big")
    return rsa.RSAPublicNumbers(e, n).public_key()


def _download_keys(team):
    """{key id: public key} from https://<team>.cloudflareaccess.com/cdn-cgi/access/certs"""
    url = f"https://{team}.cloudflareaccess.com/cdn-cgi/access/certs"
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.load(r)
    return {k["kid"]: _rsa_key(k) for k in data.get("keys", []) if k.get("kty") == "RSA"}


def _public_key(team, kid, fetch=_download_keys):
    """The team's public key with this id. Downloads again when the cache is old or the id is new
    (Cloudflare rotates keys now and then)."""
    c = _certs_cache
    fresh = c["team"] == team and time.time() - c["at"] < CERTS_TTL
    if not fresh or kid not in c["keys"]:
        try:
            c.update(team=team, at=time.time(), keys=fetch(team))
        except Exception:          # no internet / Cloudflare down: nobody gets owner rights (fail closed)
            return None
    return c["keys"].get(kid)


def owner_email(token, team=None, aud=None, emails=None, now=None, fetch=_download_keys):
    """The owner's email if `token` is a valid Access login for the admin app, otherwise None.
    Every failure (missing, malformed, wrong signature, wrong app, expired, not an owner) returns None."""
    if team is None:
        team, aud, emails = settings()
    if not (token and team and aud):
        return None
    try:
        head_b64, body_b64, sig_b64 = token.split(".")
        head = json.loads(_b64url(head_b64))
        body = json.loads(_b64url(body_b64))
        sig = _b64url(sig_b64)
    except (ValueError, TypeError):
        return None

    if head.get("alg") != "RS256":            # refuse "none" and any other algorithm
        return None
    key = _public_key(team, head.get("kid"), fetch)
    if key is None:
        return None
    try:
        key.verify(sig, f"{head_b64}.{body_b64}".encode(), padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        return None

    now = time.time() if now is None else now
    auds = body.get("aud") if isinstance(body.get("aud"), list) else [body.get("aud")]
    if body.get("iss") != f"https://{team}.cloudflareaccess.com" or aud not in auds:
        return None
    if not isinstance(body.get("exp"), (int, float)) or body["exp"] < now:
        return None
    email = str(body.get("email", "")).lower()
    if not email or (emails and email not in emails):
        return None
    return email
