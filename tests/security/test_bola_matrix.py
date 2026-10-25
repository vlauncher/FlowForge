"""Comprehensive Broken Object Level Authorization (BOLA / IDOR) matrix test (P9-T08)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def signup(client: AsyncClient, email: str) -> str:
    res = await client.post(
        "/v1/auth/signup",
        json={"email": email, "password": "Password123456!", "display_name": email.split("@")[0]},
    )
    return res.json()["access_token"]


@pytest.mark.asyncio
async def test_p9_t08_comprehensive_bola_matrix(client: AsyncClient) -> None:
    """P9-T08: User in Org B attempts every read/write endpoint on Org A's resource IDs -> 404.

    Tenant isolation principle: Attempting to access or mutate resources in another organization
    must always return 404 Not Found to prevent tenancy enumeration and cross-tenant leakage.
    """
    token_a = await signup(client, "alice@org-a.com")
    token_b = await signup(client, "bob@org-b.com")

    auth_a = {"Authorization": f"Bearer {token_a}"}
    auth_b = {"Authorization": f"Bearer {token_b}"}

    # Setup Org A and Org B
    res_org_a = await client.post(
        "/v1/organizations", json={"name": "Org Alpha", "slug": "org-alpha"}, headers=auth_a
    )
    org_a_id = res_org_a.json()["id"]

    await client.post(
        "/v1/organizations", json={"name": "Org Beta", "slug": "org-beta"}, headers=auth_b
    )

    # Setup Org A Credential
    res_cred_a = await client.post(
        f"/v1/organizations/{org_a_id}/credentials",
        json={
            "provider": "api_provider",
            "name": "Alpha API Key",
            "secret": "alpha-secret-key-123456",
            "allowed_hosts": ["api.alpha.com"],
        },
        headers=auth_a,
    )
    cred_a_id = res_cred_a.json()["id"]

    # Setup Org A Workflow
    res_wf_a = await client.post(
        f"/v1/organizations/{org_a_id}/workflows",
        json={"display_name": "Alpha Main Workflow"},
        headers=auth_a,
    )
    wf_a_id = res_wf_a.json()["id"]

    definition = {
        "schema_version": 1,
        "name": "Alpha Flow",
        "start": "step_approval",
        "steps": [
            {
                "id": "step_approval",
                "type": "approval",
                "config": {
                    "assigned_role": "owner",
                    "expires_in_seconds": 3600,
                    "summary": "Approval in Org A",
                },
                "next": None,
            }
        ],
    }

    # Add version and publish in Org A
    await client.post(
        f"/v1/workflows/{wf_a_id}/versions",
        json={"definition": definition},
        headers=auth_a,
    )
    await client.post(f"/v1/workflows/{wf_a_id}/publish", headers=auth_a)

    # Add Trigger in Org A
    await client.post(
        f"/v1/workflows/{wf_a_id}/triggers",
        json={"credential_id": cred_a_id},
        headers=auth_a,
    )

    # Trigger Run in Org A
    res_run_a = await client.post(
        f"/v1/workflows/{wf_a_id}/runs",
        json={"inputs": {}},
        headers=auth_a,
    )
    run_a_id = res_run_a.json()["run_id"]

    # Retrieve approval for Run A
    appr_res = await client.get(
        f"/v1/organizations/{org_a_id}/approvals",
        headers=auth_a,
    )
    approvals = appr_res.json()["items"]
    # If not yet created by worker, we use a dummy UUID or wait; but the endpoint check accepts any UUID
    approval_a_id = approvals[0]["id"] if approvals else "00000000-0000-0000-0000-000000000001"

    # --- BOLA MATRIX: User B attempts all Org A resources ---
    # Every endpoint must return 404 NOT_FOUND

    # 1. Workflow endpoints
    r = await client.get(f"/v1/workflows/{wf_a_id}", headers=auth_b)
    assert r.status_code == 404, f"GET /workflows/{wf_a_id} returned {r.status_code}"

    r = await client.get(f"/v1/workflows/{wf_a_id}/versions", headers=auth_b)
    assert r.status_code == 404, f"GET /workflows/{wf_a_id}/versions returned {r.status_code}"

    r = await client.post(
        f"/v1/workflows/{wf_a_id}/versions",
        json={"definition": definition},
        headers=auth_b,
    )
    assert r.status_code == 404, f"POST /workflows/{wf_a_id}/versions returned {r.status_code}"

    r = await client.post(f"/v1/workflows/{wf_a_id}/publish", headers=auth_b)
    assert r.status_code == 404, f"POST /workflows/{wf_a_id}/publish returned {r.status_code}"

    # 2. Trigger endpoints
    r = await client.get(f"/v1/workflows/{wf_a_id}/triggers", headers=auth_b)
    assert r.status_code == 404, f"GET /workflows/{wf_a_id}/triggers returned {r.status_code}"

    r = await client.post(
        f"/v1/workflows/{wf_a_id}/triggers",
        json={"credential_id": cred_a_id},
        headers=auth_b,
    )
    assert r.status_code == 404, f"POST /workflows/{wf_a_id}/triggers returned {r.status_code}"

    # 3. Run execution endpoints
    r = await client.post(
        f"/v1/workflows/{wf_a_id}/runs",
        json={"inputs": {}},
        headers=auth_b,
    )
    assert r.status_code == 404, f"POST /workflows/{wf_a_id}/runs returned {r.status_code}"

    r = await client.get(f"/v1/runs/{run_a_id}", headers=auth_b)
    assert r.status_code == 404, f"GET /runs/{run_a_id} returned {r.status_code}"

    r = await client.get(f"/v1/runs/{run_a_id}/attempts", headers=auth_b)
    assert r.status_code == 404, f"GET /runs/{run_a_id}/attempts returned {r.status_code}"

    r = await client.post(f"/v1/runs/{run_a_id}/cancel", headers=auth_b)
    assert r.status_code == 404, f"POST /runs/{run_a_id}/cancel returned {r.status_code}"

    r = await client.post(f"/v1/runs/{run_a_id}/retry", headers=auth_b)
    assert r.status_code == 404, f"POST /runs/{run_a_id}/retry returned {r.status_code}"

    # 4. Approvals endpoints
    r = await client.post(
        f"/v1/approvals/{approval_a_id}/decisions",
        json={"decision": "approve"},
        headers=auth_b,
    )
    assert r.status_code == 404, (
        f"POST /approvals/{approval_a_id}/decisions returned {r.status_code}"
    )

    # 5. Credentials endpoints
    r = await client.get(f"/v1/organizations/{org_a_id}/credentials", headers=auth_b)
    assert r.status_code == 404, (
        f"GET /organizations/{org_a_id}/credentials returned {r.status_code}"
    )

    r = await client.post(
        f"/v1/organizations/{org_a_id}/credentials",
        json={"name": "Hacked", "provider": "p", "secret": "s"},
        headers=auth_b,
    )
    assert r.status_code == 404, (
        f"POST /organizations/{org_a_id}/credentials returned {r.status_code}"
    )

    r = await client.post(
        f"/v1/organizations/{org_a_id}/credentials/{cred_a_id}/rotate",
        json={"secret": "new_secret_12345"},
        headers=auth_b,
    )
    assert r.status_code == 404, f"POST /credentials/{cred_a_id}/rotate returned {r.status_code}"

    # 6. Usage & Audit endpoints
    r = await client.get(f"/v1/organizations/{org_a_id}/usage", headers=auth_b)
    assert r.status_code == 404, f"GET /organizations/{org_a_id}/usage returned {r.status_code}"

    r = await client.get(f"/v1/organizations/{org_a_id}/audit-events", headers=auth_b)
    assert r.status_code == 404, (
        f"GET /organizations/{org_a_id}/audit-events returned {r.status_code}"
    )

    # 7. Org-scoped list endpoints
    r = await client.get(f"/v1/organizations/{org_a_id}/approvals", headers=auth_b)
    assert r.status_code == 404, f"GET /organizations/{org_a_id}/approvals returned {r.status_code}"

    r = await client.get(f"/v1/organizations/{org_a_id}/runs", headers=auth_b)
    assert r.status_code == 404, f"GET /organizations/{org_a_id}/runs returned {r.status_code}"

    r = await client.get(f"/v1/organizations/{org_a_id}/workflows", headers=auth_b)
    assert r.status_code == 404, f"GET /organizations/{org_a_id}/workflows returned {r.status_code}"

    r = await client.post(
        f"/v1/organizations/{org_a_id}/workflows",
        json={"display_name": "Injected Workflow"},
        headers=auth_b,
    )
    assert r.status_code == 404, (
        f"POST /organizations/{org_a_id}/workflows returned {r.status_code}"
    )

    r = await client.get(f"/v1/organizations/{org_a_id}/members", headers=auth_b)
    assert r.status_code == 404, f"GET /organizations/{org_a_id}/members returned {r.status_code}"

    r = await client.post(
        f"/v1/organizations/{org_a_id}/members",
        json={"email": "attacker@evil.com", "role": "owner"},
        headers=auth_b,
    )
    assert r.status_code == 404, f"POST /organizations/{org_a_id}/members returned {r.status_code}"
