# Login And Knowledge Isolation Design

## Context

Aurora currently opens directly into the workbench. The backend already has role-based permissions and route guards, but the default development identity means users do not see a login screen. The release requirement is:

- `admin / 123456` logs in as the administrator.
- Any other non-empty username and non-empty password can log in.
- The administrator sees the existing seeded documentation pages and keeps administrator capabilities.
- Non-admin users enter an empty personal knowledge base and can add their own knowledge.
- User knowledge must not leak across accounts.

## Recommended Approach

Implement a lightweight local-login layer with an HTTP-only session cookie and per-user runtime scope.

This approach reuses Aurora's existing auth payload, route permissions, document catalog, and knowledge APIs while adding the minimum production-facing login boundary needed before launch. It avoids client-only identity headers and avoids a full user-management system that would add unnecessary scope.

## User Experience

Unauthenticated visitors see a full-screen login page. The page asks for account and password, shows the default administrator credentials as onboarding copy, and has clear loading and error states.

After login:

- `admin / 123456` lands in the normal Aurora workbench.
- Other users land in the same workbench shell with member permissions.
- Their knowledge library starts empty, with upload and indexing actions available.
- The header shows the current display name and a logout action.
- Logout clears the session and front-end cached workspace state, then returns to the login page.

## Authentication Model

Add these endpoints:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`

Login rules:

- Empty username or empty password is rejected with `400`.
- Username `admin` requires password `123456`.
- Username `admin` with any other password is rejected with `401`.
- Any non-admin username with any non-empty password is accepted as a member.

Session rules:

- Store the current user in a signed HTTP-only cookie.
- Use `SameSite=Lax`.
- Mark the cookie `Secure` only when the request is HTTPS, so local development still works.
- Normalize non-admin usernames into safe IDs for storage paths and project IDs.
- Keep session payload minimal: user ID, role, display name, team ID, allowed project ID, and issued time.

## Authorization And Roles

The existing permission map remains the source of truth.

- Admin user role: `admin`
- Non-admin user role: `member`

This means admin keeps settings, logs, internal, and knowledge operations. Members keep chat, document read/write, graph read, and knowledge-base read. Because members need to build their own knowledge, this design should allow them to trigger knowledge-base rebuild for their personal scope. If the existing permission map blocks this, add `knowledge_base.operate` to `member` only if the operation is scoped to that user's own data directory.

## Knowledge Isolation

Use a scoped config derived from the authenticated user:

- Admin data directory remains `data/`.
- Admin catalog and current job files remain in `db/`.
- Non-admin user data directory becomes `data/users/<safe_user_id>/`.
- Non-admin catalog and job files become scoped under `db/users/<safe_user_id>/`.
- Non-admin vector/local index collection names receive a user-specific suffix, for example `ai_kb_docs_user_<safe_user_id>`.

The backend should derive this server-side after resolving the session. The browser must not choose its own data directory or project scope.

All routes that read or mutate documents, knowledge status, preview, graph, chat retrieval, and rebuild should use the scoped runtime config. System-level settings and logs remain admin-only through existing permissions.

## Data Flow

1. Browser loads the app.
2. App requests `GET /api/v1/system/bootstrap`.
3. If the backend returns `401`, the app renders the login page.
4. User submits credentials to `POST /api/v1/auth/login`.
5. Backend validates credentials, sets the session cookie, and returns the auth payload.
6. App invalidates bootstrap queries and loads the workbench.
7. Backend resolves each request from the session and derives the scoped config.

## Error Handling

- Login failure should show one concise message without revealing whether the username exists.
- Expired or invalid sessions should return `401`.
- Frontend request helpers should preserve the `401` response so the app can return to login.
- Scoped directory creation failures should surface as `500` and be logged.
- Knowledge operations should remain protected by existing rate-limit and concurrency guards.

## Frontend Design Direction

The login screen should feel like Aurora's operational workbench, not a marketing landing page. Use a focused split composition with a strong brand panel, concise Chinese copy, and a compact login form. Keep the design consistent with the existing light glass/teal Aurora interface, but avoid adding decorative background clutter or large unrelated hero content.

The workbench shell should stay mostly unchanged. Add a logout button near the user badge and route unauthenticated states to the login surface.

## Testing Plan

Backend tests:

- Login rejects empty username or password.
- Admin login succeeds only with `123456`.
- Non-admin login succeeds with any non-empty password.
- Unauthenticated bootstrap returns `401`.
- Admin document list includes existing seeded files.
- New non-admin document list starts empty.
- A non-admin upload appears only in that user's scoped document list.

Frontend tests:

- Initial unauthenticated app renders login.
- Admin login reaches the workbench and shows the knowledge page.
- Invalid admin password shows an error.
- Non-admin login reaches an empty knowledge library.
- Logout returns to login.

Verification:

- Run backend unit/API tests.
- Run front-end unit tests.
- Build the front-end.
- Run Playwright smoke coverage for login and knowledge isolation.

## Out Of Scope

- Registration, password reset, password hashing, and user management UI.
- Multi-admin management.
- Migration of existing seeded documents into per-user accounts.
- External SSO. Existing trusted-header mode can remain for future deployment needs.
