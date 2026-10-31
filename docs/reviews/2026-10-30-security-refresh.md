# Dependency audit refresh — 2026-10-30

The 2026-10-10 zero-finding audits are historical. Fresh npm and production
requirements audits against the locked 30d4eea candidate found seven npm package
entries and Python findings in certifi, setuptools, aiohttp, langgraph-sdk and
Pillow. Advisory records are evidence of affected versions, not exploitation.

Targeted lock changes preserve project requirements and package major versions,
except Pillow 12.3.0 → 13.0.0, the published corrected release. Python pins:
certifi 2026.10.18 and setuptools 84.1.0 in four services; Intelligence additionally
aiohttp 3.14.4, langgraph-sdk 0.4.6 and Pillow 13.0.0. The aiohttp distribution
requires yarl >=1.25.1, so its dependent yarl node also changes to 1.25.1.

Frontend: Vite 6.4.5, DOMPurify 3.4.17, undici 7.30.1 and the matching Vitest
4.1.12 package family. No audit suppression or `audit fix` was used. npm 10.9.8
repeatedly failed in Arborist with `edgesOut` while updating this lock; isolated
npm 12.2.1 generated the targeted update. The unchanged Node22/npm10 environment
successfully installed the resulting lock with npm ci. Manifest constraints and
lock root requirements remain unchanged.

Fresh validation: Backend 1104 tests, strict Mypy and Ruff; Intelligence 732;
Ingestion 1843 with 24 existing live opt-ins deselected; Vision44; all service
Ruff checks passed. Service tests used explicit closed loopback endpoints rather
than production defaults. The first non-isolated check attempt was interrupted
and retained separately; only the isolated reruns qualify these checks.
Frontend870 tests, ESLint and TypeScript passed. npm audit and all four complete
production lock exports report zero findings after the update. Project-owned
packages are omitted from PyPI lookup; all third-party production requirements
remain included. These are dependency/functional checks, not rebuilt-image,
remote CI, native GPU, factual-source or deployment acceptance.

Raw commands, before/after audit JSON, lock manifests and complete check logs:
`/data/odin-plan-20261030/evidence/` and its `audits/` directory. Browser diagnostics
and remaining release gates are tracked independently.
