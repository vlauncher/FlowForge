# Sources Studied

Checked on 2026-10-25 through web search summaries of official or standards pages (not read page by page). Re-check versions before implementing. Phase 1 entries are verified, and later phases are added as their chapters are written.

| # | Source | Type | Phase | Verified | What it taught / how it maps to code |
|---|---|---|---|---|---|
| 1 | [FastAPI: Concurrency and async/await](https://fastapi.tiangolo.com/async/) | Official docs | 1 | yes | `async def` vs `def`, never block the loop |
| 2 | [FastAPI: Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/) | Official docs | 1 | yes | In-process, so not for durable work |
| 3 | [FastAPI: Testing](https://fastapi.tiangolo.com/tutorial/testing/) | Official docs | 1 | not yet opened directly | Dependency overrides |
| 4 | [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) | IETF standard | 1 | yes | Error body shape, obsoletes RFC 7807 |
| 5 | [OpenAPI Specification](https://spec.openapis.org/oas/latest.html) | Standard | 1 | not yet opened directly | Contract baseline |
| 6 | [OpenRouter docs: free models](https://openrouter.ai/docs) | Vendor docs | 6 | partly (search summary) | `:free` IDs, 20 rpm, 50/1000 per day, paid-fallback risk |

Items 3 and 5 are listed from the roadmap but not yet opened directly. Open them before relying on details.
