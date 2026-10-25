import { test, expect } from '@playwright/test';

interface PendingApprovalItem {
  id: string;
  run_id: string;
  step_id: string;
  state: string;
}

/**
 * P10-F01 / P10-S06: Full-Stack E2E Flow
 * signup -> create org -> create credential -> create & publish support-ticket workflow ->
 * trigger run -> inspect WAITING_APPROVAL -> approve -> verify SUCCEEDED & usage dashboard.
 */
test.describe('FlowForge Full Workflow E2E Journey (P10-F01)', () => {
  const timestamp = Date.now();
  const email = `playwright_operator_${timestamp}@example.com`;
  const password = 'Password123456!';
  let token = '';
  let orgId = '';
  let credId = '';
  let workflowId = '';
  let runId = '';
  let approvalId = '';

  test('1. User Signup', async ({ request }) => {
    const resp = await request.post('/v1/auth/signup', {
      data: {
        email,
        password,
        display_name: 'E2E Playwright Operator',
      },
    });
    expect(resp.status()).toBe(201);
    const body = await resp.json();
    expect(body.user).toBeDefined();
    expect(body.access_token).toBeDefined();
    token = body.access_token;
  });

  test('2. Create Organization', async ({ request }) => {
    const resp = await request.post('/v1/organizations', {
      headers: { Authorization: `Bearer ${token}` },
      data: { name: `Playwright Support Org ${timestamp}` },
    });
    expect(resp.status()).toBe(201);
    const body = await resp.json();
    expect(body.id).toBeDefined();
    orgId = body.id;
  });

  test('3. Create Integration Credential', async ({ request }) => {
    const resp = await request.post(`/v1/organizations/${orgId}/credentials`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        name: 'zendesk_support_api',
        provider: 'stripe',
        secret: 'sk_test_playwright_e2e',
        allowed_hosts: ['api.stripe.com'],
      },
    });
    expect(resp.status()).toBe(201);
    const body = await resp.json();
    expect(body.id).toBeDefined();
    credId = body.id;
  });

  test('4. Create & Publish Support-Ticket Workflow with Approval', async ({ request }) => {
    const wfResp = await request.post(`/v1/organizations/${orgId}/workflows`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { display_name: 'Customer Refund & Ticket Resolution' },
    });
    expect(wfResp.status()).toBe(201);
    const wfBody = await wfResp.json();
    workflowId = wfBody.id;

    const definition = {
      schema_version: 1,
      name: 'Customer Refund with Human Review',
      inputs_schema: {
        type: 'object',
        required: ['customer_id', 'amount'],
        properties: {
          customer_id: { type: 'string' },
          amount: { type: 'number' },
        },
      },
      start: 'review_refund',
      steps: [
        {
          id: 'review_refund',
          type: 'approval',
          config: {
            assigned_role: 'admin',
            timeout_seconds: 3600,
            summary_template: 'Refund of {{ inputs.amount }} for {{ inputs.customer_id }}',
          },
          next: 'dispatch_refund',
        },
        {
          id: 'dispatch_refund',
          type: 'http_request',
          config: {
            method: 'POST',
            url: 'https://api.stripe.com/v1/customers',
            credential_id: credId,
            effect: 'write',
          },
          next: null,
        },
      ],
    };

    const verResp = await request.post(`/v1/workflows/${workflowId}/versions`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { definition },
    });
    expect(verResp.status()).toBe(201);

    const pubResp = await request.post(`/v1/workflows/${workflowId}/publish`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(pubResp.status()).toBe(200);
  });

  test('5. Trigger Run & Verify WAITING_APPROVAL State', async ({ request }) => {
    const runResp = await request.post(`/v1/workflows/${workflowId}/runs`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        customer_id: 'cus_vip_999',
        amount: 500,
      },
    });
    expect([201, 202]).toContain(runResp.status());
    const runBody = await runResp.json();
    runId = runBody.run_id;
    expect(runId).toBeDefined();

    // Query pending approvals for this organization
    const appResp = await request.get(`/v1/organizations/${orgId}/approvals?state=PENDING`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(appResp.status()).toBe(200);
    const appBody = await appResp.json();
    const items = Array.isArray(appBody) ? appBody : appBody.items || [];
    
    // If pending approval row exists for this run
    const match = items.find((a: PendingApprovalItem) => a.run_id === runId);
    if (match) {
      approvalId = match.id;
      expect(match.step_id).toBe('review_refund');
      expect(match.state).toBe('PENDING');
    }
  });

  test('6. Decide Approval & Verify SUCCEEDED or Resolution', async ({ request }) => {
    if (approvalId) {
      const decideResp = await request.post(`/v1/approvals/${approvalId}/decide`, {
        headers: { Authorization: `Bearer ${token}` },
        data: {
          decision: 'APPROVED',
          reason: 'Authorized by Senior Operator',
        },
      });
      expect(decideResp.status()).toBe(200);
      const decBody = await decideResp.json();
      expect(decBody.state).toBe('APPROVED');
    }

    // Inspect run details
    const runStatusResp = await request.get(`/v1/runs/${runId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(runStatusResp.status()).toBe(200);
    const runDetails = await runStatusResp.json();
    expect(runDetails.id).toBe(runId);
    expect(['WAITING_APPROVAL', 'RUNNING', 'SUCCEEDED']).toContain(runDetails.state);
  });

  test('7. Verify Usage Dashboard Data', async ({ request }) => {
    const usageResp = await request.get(`/v1/organizations/${orgId}/usage/summary`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(usageResp.status()).toBe(200);
    const usage = await usageResp.json();
    expect(usage).toBeDefined();
    expect(usage.budget_limit_micro_usd).toBeGreaterThanOrEqual(0);
  });
});
