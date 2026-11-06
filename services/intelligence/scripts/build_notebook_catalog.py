"""Build a new immutable NotebookLM catalog from existing reviewed packages.

Run from the intelligence directory: python -m scripts.build_notebook_catalog
--intel PACKAGE --methods PACKAGE --output /data/.../catalog.sqlite
"""

import argparse
import asyncio
import json
from pathlib import Path

from config import settings
from rag.notebooks import build_catalog, embed_notebook_documents


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intel", type=Path, required=True)
    parser.add_argument("--methods", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = await build_catalog(
        {"intel": args.intel, "methods": args.methods},
        args.output,
        embed=embed_notebook_documents,
        embedding_model=settings.notebook_embedding_model,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
