"""Owner login through Cloudflare Access: the token check must accept only a genuine, current login.
Makes its own test key pair, so no internet or Cloudflare account is needed.
Run from the project root: python tests/test_access_login.py"""

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402

from src import access_login as al  # noqa: E402

TEAM, AUD, OWNER, NOW = "myteam", "aud-123", "owner@example.com", 1_800_000_000
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def token(key=KEY, alg="RS256", kid="k1", **claims):
    body = {"iss": f"https://{TEAM}.cloudflareaccess.com", "aud": [AUD], "exp": NOW + 600, "email": OWNER}
    body.update(claims)
    head_body = f"{b64(json.dumps({'alg': alg, 'kid': kid}).encode())}.{b64(json.dumps(body).encode())}"
    sig = key.sign(head_body.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{head_body}.{b64(sig)}"


def fetch(team):                                   # stands in for Cloudflare's public-key download
    return {"k1": KEY.public_key()}


def check(tok, emails=frozenset({OWNER}), team=TEAM, aud=AUD):
    al._certs_cache.update(team=None, at=0.0, keys={})
    return al.owner_email(tok, team=team, aud=aud, emails=set(emails), now=NOW, fetch=fetch)


cases = [
    ("genuine owner login", check(token()), OWNER),
    ("genuine login, no owner list set", check(token(), emails=()), OWNER),
    ("email in different case", check(token(email="Owner@Example.com")), OWNER),
    ("no token", check(None), None),
    ("garbage token", check("not.a.token"), None),
    ("signed by another key (forged)", check(token(key=OTHER)), None),
    ("alg none", check(token(alg="none")), None),
    ("unknown key id", check(token(kid="zzz")), None),
    ("expired", check(token(exp=NOW - 1)), None),
    ("for another app (AUD)", check(token(aud=["other-app"])), None),
    ("from another team (iss)", check(token(iss="https://evil.cloudflareaccess.com")), None),
    ("not an owner email", check(token(email="someone@else.com")), None),
    ("feature off (no team/aud)", check(token(), team="", aud=""), None),
]
# a token whose payload was edited after signing
t = token().split(".")
t[1] = b64(json.dumps({"iss": f"https://{TEAM}.cloudflareaccess.com", "aud": [AUD], "exp": NOW + 600,
                       "email": "attacker@evil.com"}).encode())
cases.append(("payload edited after signing", al.owner_email(".".join(t), TEAM, AUD, set(), NOW, fetch), None))

failed = 0
for name, got, want in cases:
    ok = got == want
    failed += not ok
    print(("ok  " if ok else "FAIL"), name, "->", got)
print(f"\n{len(cases) - failed}/{len(cases)} passed")
sys.exit(1 if failed else 0)
