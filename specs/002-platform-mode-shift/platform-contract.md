# Platform Contract (Authoritative Pointer)

The frozen contract that this repo implements lives in the client repo:

```text
c:\code\awr-cv-match-client\specs\008-platform-mode-shift\platform-contract.md
```

**Do not edit the contract in this repo.** Treat it as read-only. Any change
must originate in the client repo and be mirrored here only if/when the client
team publishes a new version. This file exists so that linking from
[`spec.md`](./spec.md) and [`plan.md`](./plan.md) resolves locally.

If you need to inspect or diff the contract, copy it from the client repo path
above. To enforce sync, a future task can add a CI check that re-fetches and
compares.
