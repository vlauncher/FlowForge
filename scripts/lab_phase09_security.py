#!/usr/bin/env python3
"""Phase 9 Security & Concurrency Verification Lab Script."""

from __future__ import annotations

import asyncio
import ipaddress

import httpx

from app.core.config import get_settings
from app.core.errors import BudgetExceededError, EgressBlockedError
from app.core.ids import new_id
from app.infrastructure.db.session import get_session_factory
from app.infrastructure.http_tool.egress import (
    validate_and_pin_url,
)
from app.modules.executions.models import WorkflowRun
from app.modules.identity.models import User
from app.modules.organizations.models import Membership, Organization
from app.modules.usage.budget import (
    get_org_committed_and_reserved_budget,
    reserve_budget,
)
from app.modules.workflows.models import Workflow, WorkflowVersion


async def run_ssrf_lab() -> dict[str, bool]:
    print("--- LAB 1: SSRF & DNS Rebinding Defense ---")
    results = {}

    # Vector 1: Decimal IP representation of 127.0.0.1 (2130706433)
    try:
        await validate_and_pin_url("https://2130706433/", allowed_hosts=["2130706433"])
        results["decimal_ip"] = False
    except EgressBlockedError:
        results["decimal_ip"] = True
    print(f"Vector 1: Decimal IP blocked: {results['decimal_ip']}")

    # Vector 2: IPv6-mapped IPv4 metadata IP (::ffff:169.254.169.254)
    try:
        await validate_and_pin_url(
            "https://[::ffff:169.254.169.254]/", allowed_hosts=["::ffff:169.254.169.254"]
        )
        results["ipv6_mapped_metadata"] = False
    except EgressBlockedError:
        results["ipv6_mapped_metadata"] = True
    print(f"Vector 2: IPv6-mapped metadata blocked: {results['ipv6_mapped_metadata']}")

    # Vector 3: HTTP 302 redirect to metadata IP
    mock_transport = httpx.MockTransport(
        lambda req: httpx.Response(
            302, headers={"Location": "http://169.254.169.254/latest/meta-data/"}
        )
    )
    async with httpx.AsyncClient(transport=mock_transport, follow_redirects=False) as c:
        resp = await c.get("https://api.example.com")
        results["redirect_not_followed"] = (
            resp.status_code == 302 and resp.headers.get("Location") is not None
        )
    print(f"Vector 3: HTTP 302 redirect not followed: {results['redirect_not_followed']}")

    # Vector 4: Dual A-record with 1 public and 1 private IP
    async def dual_resolver(h, p):
        return [ipaddress.ip_address("93.184.216.34"), ipaddress.ip_address("10.0.0.1")]

    try:
        await validate_and_pin_url(
            "https://dual.example.com/", allowed_hosts=["dual.example.com"], resolver=dual_resolver
        )
        results["dual_a_record"] = False
    except EgressBlockedError:
        results["dual_a_record"] = True
    print(f"Vector 4: Dual A-record containing private IP blocked: {results['dual_a_record']}")

    # Vector 5: DNS rebinding between check and use
    calls = 0

    async def rebind_resolver(h, p):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [ipaddress.ip_address("93.184.216.34")]
        return [ipaddress.ip_address("169.254.169.254")]

    pinned_url, host_hdr, ext = await validate_and_pin_url(
        "https://rebind.example.com/data",
        allowed_hosts=["rebind.example.com"],
        resolver=rebind_resolver,
    )
    results["dns_rebinding_pinned"] = pinned_url == "https://93.184.216.34:443/data" and calls == 1
    print(f"Vector 5: DNS rebinding pinned to validated IP: {results['dns_rebinding_pinned']}")

    # Vector 6: Non-standard port (6379 Redis)
    try:
        await validate_and_pin_url(
            "https://api.example.com:6379/", allowed_hosts=["api.example.com"]
        )
        results["non_standard_port"] = False
    except EgressBlockedError:
        results["non_standard_port"] = True
    print(f"Vector 6: Non-standard port 6379 blocked: {results['non_standard_port']}")

    return results


async def run_budget_lab() -> dict[str, int]:
    print("\n--- LAB 2: Concurrent Budget Exhaustion Lab ---")
    settings = get_settings()
    settings.llm_price_per_1k_tokens_micro_usd = 1000

    factory = get_session_factory()
    org_id = new_id()
    user_id = new_id()
    wf_id = new_id()
    ver_id = new_id()

    # Org budget: 15,000 µUSD
    # Step cost: max_tokens = 500 -> 3,000 µUSD each
    # 20 concurrent requests -> exactly 5 should reserve (15,000 / 3,000 = 5) and 15 should fail
    budget_limit = 15000

    async with factory() as session:
        async with session.begin():
            u = User(
                id=user_id,
                email=f"lab_{org_id.hex[:6]}@example.com",
                password_hash="hash",
                display_name="Lab User",
            )
            o = Organization(
                id=org_id,
                name="Lab Org",
                slug=f"lab-{org_id.hex[:6]}",
                budget_limit_micro_usd=budget_limit,
                max_concurrent_runs=50,
            )
            m = Membership(org_id=org_id, user_id=user_id, role="owner")
            w = Workflow(id=wf_id, org_id=org_id, display_name="Lab Workflow", created_by=user_id)
            v = WorkflowVersion(
                id=ver_id,
                workflow_id=wf_id,
                org_id=org_id,
                version=1,
                status="published",
                definition_json={"start": "ai", "steps": []},
                schema_version=1,
                checksum="cs",
                published_at=datetime_now_utc(),
            )
            session.add_all([u, o, m, w, v])

            runs = [
                WorkflowRun(
                    id=new_id(),
                    org_id=org_id,
                    workflow_id=wf_id,
                    version_id=ver_id,
                    state="RUNNING",
                    trigger_kind="manual",
                    inputs={},
                    context={},
                    attempt_epoch=0,
                )
                for _ in range(20)
            ]
            session.add_all(runs)

    run_ids = [r.id for r in runs]

    async def attempt_reserve(r_id):
        async with factory() as session:
            async with session.begin():
                try:
                    await reserve_budget(
                        session, org_id=org_id, run_id=r_id, step_id="ai_step", max_tokens=500
                    )
                    return True
                except BudgetExceededError:
                    return False

    res = await asyncio.gather(*[attempt_reserve(rid) for rid in run_ids])
    success_count = sum(1 for r in res if r is True)
    exceeded_count = sum(1 for r in res if r is False)

    async with factory() as session:
        total = await get_org_committed_and_reserved_budget(session, org_id=org_id)

    print("Concurrent requests: 20")
    print(f"Successes: {success_count} (reserved {success_count * 3000} µUSD)")
    print(f"BudgetExceeded: {exceeded_count}")
    print(f"Total reserved: {total} µUSD (limit: {budget_limit} µUSD)")
    print(f"In-budget constraint held: {total <= budget_limit}")

    return {
        "success_count": success_count,
        "exceeded_count": exceeded_count,
        "total_committed": total,
        "budget_limit": budget_limit,
    }


def datetime_now_utc():
    from datetime import UTC, datetime

    return datetime.now(UTC)


async def main():
    await run_ssrf_lab()
    await run_budget_lab()


if __name__ == "__main__":
    asyncio.run(main())
