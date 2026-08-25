# Third-Party Notices

ODIN (WorldView) itself is licensed under **PolyForm Noncommercial 1.0.0**.
This file indexes third-party source that has been adapted into the tree.

| Project | Licence | Pinned commit | Full text | Adapted paths |
|---|---|---|---|---|
| [God's Eye View](https://github.com/bilawalsidhu/gods-eye-view) | MIT | `880a672` | [`LICENSES/gods-eye-view-MIT.txt`](LICENSES/gods-eye-view-MIT.txt) | `services/frontend/src/lib/{renderGovernor,labelBudget,labelQuota,labelArbiter}.ts` |

## Pointer header (required in every adapted file)

```
/**
 * Adapted from God's Eye View, commit 880a672b5e16ad3e41d318801d3a5203f9201923
 * Copyright (c) 2026 Bilawal Sidhu. MIT License — full text in
 * LICENSES/gods-eye-view-MIT.txt. See THIRD_PARTY_NOTICES.md.
 */
```

## Rule for future additions

When adapting further third-party source:

1. Place the complete licence text under `LICENSES/`.
2. Add a row to the table above.
3. Put the pointer header (or an equivalent pointing at the new `LICENSES/` file and this document) in every adapted file.
