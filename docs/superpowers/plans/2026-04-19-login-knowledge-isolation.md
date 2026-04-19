# Login Knowledge Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a launch-ready login page where `admin / 123456` sees seeded documents and every other non-empty account starts with an isolated empty knowledge base.

**Architecture:** Add server-side local sessions with an HTTP-only signed cookie. Resolve the authenticated user from either trusted headers or the local session, then derive a per-user scoped `AppConfig` before document, knowledge, graph, and chat routes touch storage. The React app treats `401` bootstrap responses as unauthenticated and renders a focused login surface.

**Tech Stack:** FastAPI, Python `hmac`/`json`/`base64`, existing `AppConfig`, React 18, TanStack Query, Vitest, Playwright.

---

## File Structure

- Create `app/services/local_auth_service.py`: credential rules, signed cookie session encode/decode, scoped config derivation.
- Modify `app/core/config.py`: add local auth cookie settings and default `AUTH_MODE=local`.
- Modify `app/core/auth.py`: resolve local session users while preserving trusted-header and disabled modes.
- Create `app/api/routes/auth.py`: login, logout, me endpoints.
- Modify `app/bootstrap/http_app.py`: include auth router.
- Modify `app/api/dependencies.py`: add `get_scoped_runtime_config`.
- Modify routes in `app/api/routes/system.py`, `documents.py`, `knowledge_base.py`, `knowledge_graph.py`, and `chat.py`: use scoped config where user data is read or written.
- Modify `frontend/src/api/client.ts`: add login/logout helpers and export `ApiError.status`.
- Create `frontend/src/pages/login-page.tsx`: full-screen login experience.
- Modify `frontend/src/app/app.tsx`: render login on `401`, add logout action, clear cached workspace state.
- Modify `frontend/src/store/app-store.ts`: add workspace reset helper.
- Test `tests/test_api_routes.py`: auth/session and knowledge isolation API coverage.
- Test `frontend/tests/auth-login.spec.ts`: login, invalid admin password, user empty knowledge, logout.
- Update existing Playwright tests to log in before navigating.

## Task 1: Backend Local Session Service

**Files:**
- Create: `app/services/local_auth_service.py`
- Modify: `app/core/config.py`
- Modify: `app/core/auth.py`
- Test: `tests/test_api_routes.py`

- [ ] **Step 1: Write failing tests**

Add tests for admin login, wrong admin password, member login, unauthenticated bootstrap, and member scoped empty documents. Use `auth_mode="local"` in the test config and `TestClient(app)` without trusted headers.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m unittest tests.test_api_routes.ApiRouteTests.test_local_auth_login_rules tests.test_api_routes.ApiRouteTests.test_local_auth_scopes_member_documents`

Expected: FAIL because `/api/v1/auth/login` does not exist and bootstrap still resolves the development user.

- [ ] **Step 3: Implement local auth primitives**

`local_auth_service.py` must provide:

```python
AUTH_COOKIE_NAME = "aurora_session"

def authenticate_local_user(username: str, password: str, config: AppConfig) -> AuthenticatedUser:
    ...

def create_session_token(user: AuthenticatedUser, config: AppConfig) -> str:
    ...

def resolve_session_user(request: Request, config: AppConfig) -> AuthenticatedUser:
    ...

def clear_session_cookie(response: Response, config: AppConfig) -> None:
    ...

def derive_user_scoped_config(config: AppConfig, user: AuthenticatedUser) -> AppConfig:
    ...
```

Use HMAC SHA-256 over compact JSON. Admin keeps `data_dir=config.data_dir`, `db_dir=config.db_dir`, `collection_name=config.collection_name`; members use `data/users/<safe_user_id>`, `db/users/<safe_user_id>`, and `collection_name + "_user_" + safe_user_id`.

- [ ] **Step 4: Wire config and auth resolver**

Add `auth_session_secret`, `auth_session_cookie_name`, `auth_session_max_age_seconds`, and default `auth_mode="local"` to `AppConfig`. In `resolve_authenticated_user`, add local mode that calls `resolve_session_user`.

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m unittest tests.test_api_routes.ApiRouteTests.test_local_auth_login_rules tests.test_api_routes.ApiRouteTests.test_local_auth_scopes_member_documents`

Expected: PASS.

## Task 2: Auth Routes And Scoped Dependencies

**Files:**
- Create: `app/api/routes/auth.py`
- Modify: `app/bootstrap/http_app.py`
- Modify: `app/api/dependencies.py`
- Modify: `app/api/routes/system.py`
- Modify: `app/api/routes/documents.py`
- Modify: `app/api/routes/knowledge_base.py`
- Modify: `app/api/routes/knowledge_graph.py`
- Modify: `app/api/routes/chat.py`
- Test: `tests/test_api_routes.py`

- [ ] **Step 1: Write failing scoped route tests**

Add tests that log in as `admin` and see seeded documents, log in as `alice` and see zero documents, upload as `alice`, then log in as `bob` and still see zero documents.

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m unittest tests.test_api_routes.ApiRouteTests.test_local_user_upload_is_isolated`

Expected: FAIL because routes still use the unscoped base config.

- [ ] **Step 3: Implement routes and dependency**

Create `/api/v1/auth/login`, `/api/v1/auth/logout`, `/api/v1/auth/me`. Add `get_scoped_runtime_config(config, user)` in dependencies and use it in routes that touch knowledge data. Use the base config for app-wide settings and logs.

- [ ] **Step 4: Allow scoped member rebuild**

If a route uses `knowledge_base.operate`, allow `member` users to run scoped rebuild by adding that permission to the member role. Settings, logs, and internal routes stay admin-only.

- [ ] **Step 5: Run tests to verify pass**

Run: `python -m unittest tests.test_api_routes.ApiRouteTests.test_local_user_upload_is_isolated tests.test_api_routes.ApiRouteTests.test_member_cannot_access_admin_operations`

Expected: PASS, with member still blocked from settings, logs, and internal routes.

## Task 3: Frontend Login Flow

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/app/app.tsx`
- Modify: `frontend/src/store/app-store.ts`
- Create: `frontend/src/pages/login-page.tsx`
- Test: `frontend/tests/auth-login.spec.ts`

- [ ] **Step 1: Write failing Playwright tests**

Cover initial login screen, valid admin login, invalid admin password, non-admin empty knowledge page, and logout.

- [ ] **Step 2: Run tests to verify failure**

Run: `npm --prefix frontend run test:e2e -- auth-login.spec.ts`

Expected: FAIL because there is no login UI.

- [ ] **Step 3: Implement API helpers and login page**

Add `login(username, password)`, `logout()`, and `getCurrentAuth()` to the client. Login page should use Chinese user-facing copy, stable `data-testid` hooks, and existing Aurora visual language without a marketing hero.

- [ ] **Step 4: Wire app auth state**

In `App`, render login when bootstrap returns `401`; after login, invalidate `workspace-bootstrap`; after logout, clear query cache and reset app store.

- [ ] **Step 5: Run tests to verify pass**

Run: `npm --prefix frontend run test:e2e -- auth-login.spec.ts`

Expected: PASS.

## Task 4: Existing Test And E2E Compatibility

**Files:**
- Modify: `tests/test_api_routes.py`
- Modify: `frontend/tests/*.spec.ts`

- [ ] **Step 1: Update test fixtures**

Backend tests that rely on trusted headers should keep `auth_mode="trusted_header"`. New local auth tests should create a separate `TestClient` without default headers.

- [ ] **Step 2: Add Playwright login helper**

Existing Playwright specs should log in as admin before navigating directly to protected workspaces.

- [ ] **Step 3: Run focused suites**

Run: `python -m unittest tests.test_api_routes`

Run: `npm --prefix frontend run test`

Run: `npm --prefix frontend run build`

Expected: all pass.

## Task 5: Final Verification

**Files:**
- No new files expected.

- [ ] **Step 1: Run complete verification**

Run: `.\verify.ps1`

Expected: backend tests, frontend tests, build, and Playwright checks pass.

- [ ] **Step 2: Inspect git state**

Run: `git status --short`

Expected: only intentional implementation files are modified; existing unrelated untracked files remain untouched.

- [ ] **Step 3: Commit implementation**

Run:

```bash
git add app frontend tests docs/superpowers/plans/2026-04-19-login-knowledge-isolation.md
git commit -m "Add local login and user knowledge isolation"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: login rules, admin seeded docs, non-admin empty knowledge, session cookie, scoped storage, logout, and tests are all mapped to tasks.
- Placeholder scan: no unfinished-marker language remains.
- Type consistency: function names and route names match the planned files.
