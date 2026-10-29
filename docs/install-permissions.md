# Installer onboarding: how to configure Mac Control approvals in ChatGPT

Verified against OpenAI Help Center, 2026-10-20.
Source: https://help.openai.com/en/articles/20001495-managing-app-permissions-in-chatgpt
Background: https://help.openai.com/en/articles/11487775-apps-in-chatgpt

## Where to find the setting

1. In ChatGPT open **Profile → Settings**.
2. Look for **Plugins → Permissions** to set a default. Some interfaces
   instead show **Apps** with app preferences.
3. For Mac Control specifically, open its connected app/plugin settings.
   If the interface shows **Connected accounts**, open the connected
   account's **••• → Settings → Permissions**. For a single-account
   app the Permissions control may be on the app page itself.
4. Choose the desired permission mode and use **Save** where offered.
   A per-app or per-account override takes precedence over the default.

The exact menu, account eligibility and availability of options can vary by
account and workspace. The installer should detect / explain these variants
rather than present one assumed route.

## What the modes mean

- **Always ask / Спрашивать всегда:** ChatGPT asks before supported app actions.
- **Allow read actions / Разрешить чтение:** read actions can run without
  confirmation, changes still request approval.
- **Allow low-risk actions / Разрешить низкорисковые:** low-risk actions
  proceed automatically where eligible; higher-risk actions may prompt or
  be denied.
- **Allow all actions / Разрешить всё:** eligible app actions may run without
  another approval prompt. Not available in every account or workspace.

**Important:** these settings control *when ChatGPT asks*, not the operating
system permissions or the set of actions Mac Control exposes. Some calls can
still be blocked automatically even with Allow all; written consent in the
conversation does not override platform safety controls.

## Observed Mac Control behavior, controlled tests, 2026-10-20

- Fake bearer credential: four scenarios executed in each permission mode;
  approval was requested in the confirm mode, not in Allow all.
- Real LiteLLM credential: requests blocked under Allow all in two scenarios;
  requests with manual confirmation succeeded in two scenarios.
- Pre-consent in chat did not visibly change the outcome.

These outcomes are observations, not a guarantee of future policy behavior.
Mac Control must not implement another approval UI or a redundant catalog of
one-command handlers to try to change these outcomes.

## Acceptance criteria for installer UX

- Expose instructions after connecting to ChatGPT.
- User can locate per-app and default approval settings.
- Explain security trade-off without preselecting a more permissive mode.
- Link to the official Help Center; update menu screenshots for the release UI.
- One simple non-sensitive read-only test confirms the connection is working.
