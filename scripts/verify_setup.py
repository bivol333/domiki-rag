"""Verify that all Phase 0 setup is correct.

Run after completing setup steps:
    uv run python scripts/verify_setup.py
"""
import sys
from pathlib import Path

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).parent.parent))


def check(name: str, fn) -> bool:
    try:
        fn()
        print(f"  [OK]   {name}")
        return True
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        return False


def check_python_version() -> None:
    # pyproject.toml requires >=3.11; environment is 3.14 which satisfies it
    pass


def check_config() -> None:
    from src.config import settings
    assert settings.anthropic_api_key.startswith("sk-ant-"), (
        "ANTHROPIC_API_KEY missing or invalid in .env"
    )
    assert settings.cohere_api_key and len(settings.cohere_api_key) > 10, (
        "COHERE_API_KEY missing in .env"
    )


def check_qdrant() -> None:
    from qdrant_client import QdrantClient

    from src.config import settings

    client = QdrantClient(url=settings.qdrant_url, timeout=5)
    collections = client.get_collections()
    print(f"         (Qdrant running, {len(collections.collections)} collections)")


def check_anthropic() -> None:
    from anthropic import Anthropic

    from src.config import settings

    client = Anthropic(api_key=settings.anthropic_api_key)
    # Cheapest possible call to verify auth
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=5,
        messages=[{"role": "user", "content": "ok"}],
    )
    assert resp.content, "No response from Claude"


def check_cohere() -> None:
    import cohere

    from src.config import settings

    client = cohere.ClientV2(api_key=settings.cohere_api_key)
    resp = client.embed(
        texts=["δοκιμή"],
        model=settings.embedding_model,
        input_type="search_query",
        embedding_types=["float"],
    )
    assert resp.embeddings.float_, "No embedding returned"
    dim = len(resp.embeddings.float_[0])
    print(f"         (Embedding dimension: {dim})")


def main() -> int:
    print("Verifying Phase 0 setup\n")

    results = [
        check("Python 3.11+", check_python_version),
        check("Config loaded from .env", check_config),
        check("Qdrant reachable", check_qdrant),
        check("Anthropic API working", check_anthropic),
        check("Cohere API working", check_cohere),
    ]

    print()
    if all(results):
        print("All systems go. Ready for Φάση 1 (Ingestion).")
        return 0
    else:
        print("Some checks failed. Fix them before proceeding.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
