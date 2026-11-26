"""JWT + bcrypt + RBAC.  Ажиллуулах: python -m pytest backend/tests -q"""
import os
import sys
import time

import jwt
import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auth  # noqa: E402


def test_password_hash_roundtrip():
    h = auth.hash_password("s3cret!")
    assert auth.is_hashed(h) and h != "s3cret!"
    assert auth.verify_password("s3cret!", h)
    assert not auth.verify_password("wrong", h)


def test_plaintext_is_never_accepted_as_hash():
    assert not auth.verify_password("123456", "123456")


def test_token_roundtrip_and_role():
    claims = auth.decode_token(auth.issue_token("B22FA1260", "student", "Г.Билгээ"))
    assert claims["sub"] == "B22FA1260" and claims["role"] == "student"


def test_bearer_prefix_and_garbage():
    tok = auth.issue_token("1", "teacher")
    assert auth.decode_token("Bearer " + tok)["role"] == "teacher"
    assert auth.decode_token("not-a-token") is None
    assert auth.decode_token(None) is None


def test_expired_and_forged_tokens_rejected():
    expired = jwt.encode({"sub": "x", "role": "student", "exp": int(time.time()) - 10}, auth._SECRET, "HS256")
    assert auth.decode_token(expired) is None
    forged = jwt.encode({"sub": "x", "role": "teacher", "exp": int(time.time()) + 60}, "other-secret", "HS256")
    assert auth.decode_token(forged) is None


def test_unknown_role_rejected():
    tok = jwt.encode({"sub": "x", "role": "admin", "exp": int(time.time()) + 60}, auth._SECRET, "HS256")
    assert auth.decode_token(tok) is None


def test_require_enforces_role():
    student = "Bearer " + auth.issue_token("B1", "student")
    assert auth.require_student(authorization=student)["sub"] == "B1"
    with pytest.raises(HTTPException) as e:
        auth.require_teacher(authorization=student)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        auth.require_teacher(authorization=None)
    assert e.value.status_code == 401
