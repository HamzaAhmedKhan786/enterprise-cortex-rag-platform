# Accounts, administration and organization guide

Implemented 2026-11-01 on `development`. The application still uses Streamlit and the existing FastAPI companion service; no extra frontend framework or shared administrator credentials are introduced.

## Where to go

- **My Profile:** Streamlit sidebar → My Profile, or `http://localhost:8501/?section=My%20Profile`. The companion route is `http://localhost:8503/account/profile`.
- **Account Settings:** sidebar → Account Settings, or companion `/account/settings`.
- **Admin Dashboard:** authorized accounts see the sidebar item; companion URL `http://localhost:8503/admin`. A current role check and ten-minute password verification protect the user directory and user actions.
- **Organizations / Team Members:** sidebar → Organization / Team Members. Companion `/organizations` lists only the signed-in account's organizations and supports emailed invitation acceptance.
- **Billing:** sidebar → Subscriptions or My Profile → Manage subscription. The existing `/workspace/settings/billing` pages show overview, payment methods, invoices and usage.

Sidebar URLs carry only navigation state (`section`), never authentication identity. Direct protected links still require authentication. Back/forward/refresh read the requested section and recheck account status/roles. Links from the workspace to the companion service use a one-use, 60-second random ticket, stored only as a hash. The ticket travels in a URL fragment, is removed before a CSRF-protected POST, and binds the new session to the authenticated workspace account. IDs, email parameters and redirects cannot authenticate a user. An expired ticket requires a fresh link from the workspace.

## Existing primary administrator

Sign in normally with your **existing Cortex email and password**. The server recognizes the existing immutable account ID configured by `CORTEX_ADMIN_USER_ID`; matching an email never grants a role. The configured value is present in this environment and has not been replaced with a QA account or shared credential.

Open Admin Dashboard and re-enter your own password. Search by name/email, paginate 25 users per page, select a user, and inspect safe account metadata, organization memberships, subscription status and the latest 100 activity records. Super Admin can assign/revoke platform roles, activate/suspend/deactivate accounts and revoke sessions after confirmation. These changes invalidate the target's existing sessions. Primary and last active Super Admin protections apply in the database transaction. Passwords/hashes, provider secrets, session tickets and customer documents are never displayed in the directory.

## Roles and permissions

| Scope / role | Permissions |
|---|---|
| Platform Super Admin | Verified user-directory access; role/status/session administration; permitted billing oversight. No automatic access to customer document contents. |
| Platform Admin | Verified read access to safe user-directory metadata; cannot promote, suspend or revoke users. |
| Organization Owner | Manage organization, owners/managers, invitations, teams and shared data; transfer ownership; confirmed deletion when no shared datasets remain. |
| Organization Manager | Manage organization metadata, invite Members/Viewers, manage their memberships and teams, and manage shared data. Cannot promote owners/managers. |
| Organization Member | Read shared data, share own private datasets and build organization indexes. |
| Organization Viewer | Read shared datasets/reports and ask evidence questions; cannot share, index, delete or manage membership. |

Organization roles never grant platform privileges. The profile's editable company name is descriptive text and does not create membership. A team groups current organization members; team membership does not expand the organization data boundary or implement per-team document ACLs.

All named Super Admin accounts can administer billing after recent password verification, using the same proof as the user directory. Platform Admin is read-only and cannot mutate billing. Shared-credential Snowflake/logistics operations retain the explicit operator-ID restriction; delegated billing access never grants warehouse credentials.

## Verified email flows

Configure the following environment variables, then restart both services:

```dotenv
CORTEX_ADMIN_USER_ID=<existing immutable account ID>
BILLING_BASE_URL=http://localhost:8503
SMTP_HOST=
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_FROM=
SMTP_USERNAME=
SMTP_PASSWORD=
```

`SMTP_SECURITY` supports `starttls` (default), `ssl` (normally port 465), or `local` for a loopback-only development mail receiver. Both TLS modes validate certificates. Use HTTPS for public `BILLING_BASE_URL`. Keep keys/passwords in ignored `.env` or a deployment secret manager.

- Forgot password: sign-in → Forgot password, or `/auth/reset`. The response does not reveal account existence. A single-use 15-minute email link opens `/auth/email`; the user chooses a new password. It invalidates older sessions.
- Verify current email: My Profile → Send email verification.
- Change email: Account Settings → new address + current password. The old address remains in effect until the new address's emailed token is confirmed. Verification invalidates old sessions; sign in again.
- Invitations: an authorized organization manager/owner sends an email-scoped, 24-hour token. The recipient registers/signs in with that email, then opens the invitation. Token possession verifies that email; an existing member's role is never overwritten by an old invitation. Acceptance rechecks the inviter's current permission.

Tokens are hashed, purpose-bound, expiring and consumed transactionally. Email requests are throttled to five per target/purpose per fifteen minutes. Password changes invalidate pending email tokens. Without SMTP, verified delivery actions are explicitly unavailable; no account changes occur and no false email-sent claim is made. Automated delivery tests use mocked transport; **no real SMTP delivery was performed**.

## Organization data isolation

Upload through the existing scanned Data studio workflow, then explicitly share your private dataset from Organization. Sharing binds that existing immutable dataset to one organization and removes it from personal dataset listings/retrieval. Its raw bytes and index IDs are preserved. Current organization membership is required for reads; writes additionally require a non-Viewer role. Sharing with another organization is rejected. Re-upload deduplication cannot expose an organization-bound source through the private workspace.

Organization has filtered date/product/customer reports, safe CSV exports, a product revenue chart, document text preview, BM25 indexing and Carol evidence queries. The organization ID is passed explicitly through the retrieval workflow. Conversations/runs are tagged with their organization and remain per-user; removal from membership blocks subsequent server access. Personal history excludes organization conversations. Platform directory access does not bypass these content ACLs.

Current subscription, usage quotas, migration credentials and billing associations remain **per account**, not a pooled organization subscription. Uploads shared with an organization continue counting against the original uploader's limits. Teams do not yet provide separate document entitlements. Copies already exported by a legitimately authorized user cannot be recalled on revocation.

## Account deletion and retention

Account Settings requires the current password plus `DELETE MY ACCOUNT`. Sole organization owners must transfer ownership/delete their empty organization first. Super Admin privileges must be transferred/removed first. Pending checkout must expire, and an existing subscription must end in Stripe before deletion; scheduling cancellation alone is insufficient.

Deletion removes private uploads/chunks, profile, personal and owned organization conversations, local migration/logistics snapshots, session/verification tokens and memberships. Shared organization data remains organization-owned. The user row becomes a disabled, anonymized tombstone so retained financial/audit references and shared-source ownership keep referential integrity. Financial Stripe references/invoices/usage/audit metadata follow the operator's separate retention policy. This action does not delete the Stripe customer at the provider or purge backups; those require an operator retention/deletion procedure.

## Schema and compatibility

`identity_schema.py` is additive and repeatable. Existing users, passwords, datasets, chunks, billing IDs and subscriptions are preserved. Users gain account status, last login, email-verification/revocation timestamps and an Argon2 hash. Legacy PBKDF2 is verified with the original parameters, then upgraded to Argon2id after successful login; new/changed/reset passwords use `argon2-cffi`. Existing accounts are not reset, reseeded or automatically verified by email.

New tables: `profiles`, `platform_roles`, `auth_steps`, `email_tokens`, `email_attempts`, `auth_bridges`, `organizations`, `memberships`, `invitations`, `teams`, `team_members`, `organization_datasets`. Messages and runs gain an organization scope; companion sessions gain an admin proof. Compound foreign keys keep team membership inside its organization. The primary role is bootstrapped only for an existing active configured user ID.

## PostgreSQL production path and limitations

1. Back up SQLite and verify restore. Export all immutable IDs and join tables without re-keying Stripe references. Convert timestamps to UTC `timestamptz`, binary payloads to controlled object-storage references, and migrate constraints/indexes explicitly.
2. Introduce versioned PostgreSQL migrations and transactional data-access services. Set authenticated actor and organization context locally in each transaction; enforce owner/member policies with RLS, including chunks, conversation history and reports. Test policies with an application role that cannot bypass RLS.
3. Use transactional counters/row locks for quotas and last-owner/admin guards. Move email delivery to a reliable encrypted queue/outbox with retries, idempotency and delivery monitoring; keep token expiry/consumption atomic.
4. Add TLS, edge/IP/global abuse limits, MFA/WebAuthn or OIDC/SSO, managed secrets, encrypted backups/object storage, a tested retention process and security review before public multi-tenant deployment.

SQLite is still single-node; application ACLs provide tested isolation but are not PostgreSQL RLS. SMTP delivery, live Stripe payments, MFA/SSO, organization-pooled billing, per-team content permissions and avatar upload are not claimed as implemented/verified capabilities. Normal account email verification is offered, but existing accounts retain sign-in access pending verification.

## Screenshots and validation

Screenshots `26`–`34` use **an isolated QA database and ephemeral test accounts**, not the real user directory. No production account was impersonated and no default admin is seeded by the application. `scripts/prepare_accounts_capture.py --isolated-qa` creates these fixtures only under ignored `data/private/account-capture`; `scripts/capture_accounts.cjs` exercises actual browser login, profile persistence, verified handoff, admin step-up, navigation and mobile layout against separate QA ports 8511/8513. Production uses 8501/8503. See VALIDATION.md for final test results.

## Tester access without shared credentials

Have every tester register an individual account. As the primary administrator, open Admin Dashboard, verify your password, select that tester, choose **Platform role → super_admin**, confirm, and apply. The tester signs in with their own password and verifies it on `/admin/billing`. The same recent companion-service proof works across directory and billing. Member tests ordinary customer subscriptions; Admin can review user metadata; reserve Super Admin for trusted privileged testers. Demotion revokes the target's sessions immediately. Primary and last-active-Super-Admin protections still apply. Organization membership does not grant platform or financial privileges.

Role, account-status and session actions now use separate forms with matching values and user-bound confirmation state, preventing the earlier ambiguous Action/Value combinations. Your existing configured primary user remains intact.
