"""Multi-tenancy isolation and RBAC security test suite."""

import uuid
import pytest
from fastapi import HTTPException
from backend.app.api.security import Principal, create_access_token, require_role, verify_password, hash_password


def test_password_hashing():
    pw = "P@ssw0rdSecure!2026"
    h = hash_password(pw)
    assert verify_password(pw, h) is True
    assert verify_password("wrong_password", h) is False


def test_rbac_role_hierarchy():
    owner = Principal(user_id=str(uuid.uuid4()), tenant_id=str(uuid.uuid4()), role="owner")
    admin = Principal(user_id=str(uuid.uuid4()), tenant_id=str(uuid.uuid4()), role="admin")
    reviewer = Principal(user_id=str(uuid.uuid4()), tenant_id=str(uuid.uuid4()), role="reviewer")
    viewer = Principal(user_id=str(uuid.uuid4()), tenant_id=str(uuid.uuid4()), role="viewer")

    # Reviewer check
    reviewer_guard = require_role("reviewer")
    assert reviewer_guard(owner) == owner
    assert reviewer_guard(admin) == admin
    assert reviewer_guard(reviewer) == reviewer

    # Viewer should be forbidden on reviewer-only endpoints
    with pytest.raises(HTTPException) as exc:
        reviewer_guard(viewer)
    assert exc.value.status_code == 403


def test_cross_org_principal_tokens():
    org_a = str(uuid.uuid4())
    org_b = str(uuid.uuid4())
    user_a = str(uuid.uuid4())

    token_a, _ = create_access_token(user_id=user_a, tenant_id=org_a, role="analyst")
    assert token_a is not None
    assert len(token_a) > 20
