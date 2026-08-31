---
name: musein-cli
description: Use the native Musein CLI provider in OpenMontage for quoted, recoverable multi-model video generation. Read before calling musein_video, selecting a Musein model, approving points, collecting a timed-out task, or reconciling an unknown submission.
metadata:
  openclaw:
    requires:
      bins:
        - musein
---

# Musein CLI Provider

Use `musein_video` through `video_selector`. When a production must remain on
Musein, pass both `preferred_provider: "musein"` and
`allowed_providers: ["musein"]`; the allow-list is the hard provider boundary.

Musein CLI owns authentication, endpoint selection, uploads, its local task
ledger, and provider recovery. OpenMontage must never copy a Musein key into its
own `.env`, put a key on argv, or call the underlying provider APIs directly.

## Authentication and account boundary

For an interactive workstation, sign in once:

```powershell
musein login --method key
musein whoami --json
```

The login command reads the key without echo and stores credentials per
endpoint. `MUSEIN_KEY` and `MUSEIN_TOKEN` are supported by Musein for CI, but
they belong to the CLI process, not OpenMontage configuration.

Do not change `MUSEIN_ENDPOINT`, the configured billing team, or `--team`
silently. A different endpoint is a different account system; a different team
can charge a different wallet.

## Preflight every paid generation

1. Run `musein models --type video --json`, then
   `musein models show <model_id> --json`. The catalog shows availability, not
   account entitlement; the exact dry run is the entitlement and price check.
2. Pass model-declared defaults explicitly when they affect the brief,
   especially `generate_audio`.
3. Call `musein_video.dry_run()` with the exact prompt, references, parameters,
   and model. Dry run submits nothing and spends no points.
4. Show the resolved model and `points_estimated`. Pass that estimate as
   `approved_points` only after approval.
5. Generate once. The provider re-quotes immediately before submission and
   stops if the estimate increased above the approved value.
6. Inspect the saved MP4 plus returned `task_id`, actual `model`, `overrides`,
   and usage.

The quote is indicative. `usage.points_consumed` in a completed task is the
authoritative charge. Never calculate consumption from before/after balances.
OpenMontage reports USD only when the operator explicitly configures
`MUSEIN_USD_PER_POINT`; otherwise the point amount stays exact and USD remains
unknown.

## Model fallback

OpenMontage uses `--strict-model` by default because its paid-call approval is
for an exact model. To allow Musein's availability fallback, the caller must set
`allow_model_fallback: true` and pass `approved_model` equal to the model
returned by the approved dry run. Always report the final `model_id` and any
server `overrides`; never describe a substituted model as the requested one.

## References and outputs

Musein references may be HTTPS URLs, local paths, or
`task:<task_id>[:<index>]`. Local uploads are endpoint-dependent. If an endpoint
returns `not_implemented`, use a reachable HTTPS URL or a previous task
artifact; do not switch endpoints automatically.

Write the result into the active OpenMontage project tree. The provider
downloads into a unique staging directory, validates that exactly one playable
MP4 exists, then moves it to `output_path`. Existing outputs are never
overwritten.

## Recovery contract

Never automatically retry a paid Musein generation.

| Exit | Meaning | Required action |
|---:|---|---|
| 2 | Invalid/local unsupported request | Correct the request; no blind retry |
| 3 | Not authenticated | Repair CLI login or its CI credential |
| 4 | Insufficient points | Obtain approval/top up or choose a cheaper request |
| 5 | Provider task failed | Inspect failure; a new generation is a new paid action |
| 6 | Wait elapsed; task still exists | Call `musein_video` with `task_action: "collect"` and the same `task_id` |
| 9 | Dispatch outcome unknown | Call `task_action: "resolve"` with the returned resolution id; never resubmit |
| 10 | Service/network unavailable | Inspect task/ledger state before deciding whether any new submit is safe |

`collect` maps to `musein task get <task_id> --wait` and cannot create a new
generation charge. `resolve` maps to `musein task resolve <id>` and is strictly
read-only. Slow tasks are not failed tasks: let the wait budget expire and
collect the same task instead of killing or replaying it.

## Native OpenMontage calls

```python
quote = musein_video.dry_run({
    "prompt": "A locked-off portrait; soft window light; subtle breathing",
    "model": "<live-model-id>",
    "duration": 5,
    "aspect_ratio": "9:16",
    "generate_audio": False,
    "output_path": "projects/demo/shot-01.mp4",
})

result = musein_video.execute({
    "task_action": "generate",
    "prompt": "A locked-off portrait; soft window light; subtle breathing",
    "model": "<live-model-id>",
    "duration": 5,
    "aspect_ratio": "9:16",
    "generate_audio": False,
    "approved_points": quote["points_estimated"],
    "output_path": "projects/demo/shot-01.mp4",
})
```

No scheduled or background traffic is part of this provider. It makes zero
calls while idle.
