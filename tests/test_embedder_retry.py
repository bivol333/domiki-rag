"""Tests for embedder retry logic and inter-batch delay."""
from unittest.mock import MagicMock, call, patch

import cohere
import pytest

from src.indexing.embedder import _MAX_RETRIES, _embed_batch, embed_chunks


def _make_cohere_client(side_effects: list) -> MagicMock:
    """Return a mock ClientV2 whose .embed() raises or returns per side_effects."""
    client = MagicMock(spec=cohere.ClientV2)
    client.embed.side_effect = side_effects
    return client


def _rate_limit_exc() -> cohere.TooManyRequestsError:
    """Construct a TooManyRequestsError using its actual signature (body only)."""
    return cohere.TooManyRequestsError(body="rate limit exceeded")


def _ok_response(n: int = 2) -> MagicMock:
    """Return a mock Cohere embed response with n float vectors of dim 3."""
    resp = MagicMock()
    resp.embeddings.float_ = [[0.1, 0.2, 0.3]] * n
    return resp


class TestEmbedBatchRetry:
    def test_succeeds_first_attempt(self):
        client = _make_cohere_client([_ok_response(2)])
        result = _embed_batch(client, ["a", "b"], "search_document", label="test")
        assert len(result) == 2
        assert client.embed.call_count == 1

    def test_retries_on_rate_limit_then_succeeds(self):
        """Single 429 → retry → success."""
        client = _make_cohere_client([
            _rate_limit_exc(),
            _ok_response(1),
        ])
        with patch("src.indexing.embedder.time.sleep") as mock_sleep:
            result = _embed_batch(client, ["x"], "search_document", label="test")
        assert len(result) == 1
        assert client.embed.call_count == 2
        mock_sleep.assert_called_once_with(1.0)  # first backoff delay

    def test_retries_multiple_times_on_rate_limit(self):
        """Three 429s → fourth attempt succeeds."""
        client = _make_cohere_client([
            _rate_limit_exc(),
            _rate_limit_exc(),
            _rate_limit_exc(),
            _ok_response(1),
        ])
        with patch("src.indexing.embedder.time.sleep") as mock_sleep:
            result = _embed_batch(client, ["x"], "search_document", label="test")
        assert len(result) == 1
        assert client.embed.call_count == 4
        # Backoff: 1s, 2s, 4s
        assert mock_sleep.call_args_list == [call(1.0), call(2.0), call(4.0)]

    def test_raises_after_max_retries_rate_limit(self):
        """Exhausting all retries on 429 re-raises TooManyRequestsError."""
        exc = _rate_limit_exc()
        client = _make_cohere_client([exc] * _MAX_RETRIES)
        with patch("src.indexing.embedder.time.sleep"):
            with pytest.raises(cohere.TooManyRequestsError):
                _embed_batch(client, ["x"], "search_document", label="test")
        assert client.embed.call_count == _MAX_RETRIES

    def test_raises_after_max_retries_generic_error(self):
        """Generic errors are wrapped in RuntimeError after all retries."""
        client = _make_cohere_client([RuntimeError("server error")] * _MAX_RETRIES)
        with patch("src.indexing.embedder.time.sleep"):
            with pytest.raises(RuntimeError, match="Embedding failed after"):
                _embed_batch(client, ["x"], "search_document", label="test")
        assert client.embed.call_count == _MAX_RETRIES

    def test_backoff_sequence_is_exponential(self):
        """Sleep delays follow 1 → 2 → 4 → 8 → (5th fails) sequence."""
        fails = _MAX_RETRIES - 1  # succeed on last attempt
        client = _make_cohere_client(
            [_rate_limit_exc()] * fails + [_ok_response(1)]
        )
        with patch("src.indexing.embedder.time.sleep") as mock_sleep:
            _embed_batch(client, ["x"], "search_document", label="test")
        delays = [c.args[0] for c in mock_sleep.call_args_list]
        # Verify exponential: each delay is double the previous
        for i in range(1, len(delays)):
            assert delays[i] == delays[i - 1] * 2, f"delay[{i}]={delays[i]} != {delays[i-1]*2}"

    def test_max_retries_is_five(self):
        """Sanity-check the module constant."""
        assert _MAX_RETRIES == 5


class TestEmbedChunksInterBatchDelay:
    def test_no_delay_for_single_batch(self):
        """With only one batch, no inter-batch sleep is needed."""
        with (
            patch("src.indexing.embedder._get_client") as mock_get,
            patch("src.indexing.embedder.time.sleep") as mock_sleep,
        ):
            client = MagicMock()
            client.embed.return_value = _ok_response(2)
            mock_get.return_value = client
            embed_chunks(["a", "b"], source_hint="test")
        mock_sleep.assert_not_called()

    def test_delay_applied_between_batches(self):
        """Two batches must have exactly one inter-batch sleep call."""
        from src.indexing.embedder import _BATCH_SIZE, _INTER_BATCH_DELAY
        n_texts = _BATCH_SIZE + 1  # forces exactly 2 batches

        with (
            patch("src.indexing.embedder._get_client") as mock_get,
            patch("src.indexing.embedder.time.sleep") as mock_sleep,
        ):
            client = MagicMock()
            client.embed.return_value = _ok_response(_BATCH_SIZE)
            mock_get.return_value = client
            embed_chunks(["x"] * n_texts, source_hint="test")

        # Exactly one inter-batch delay (before the second batch)
        assert mock_sleep.call_count == 1
        assert mock_sleep.call_args_list[0] == call(_INTER_BATCH_DELAY)

    def test_inter_batch_delay_is_reasonable(self):
        """Delay must be between 0.1 s and 2 s (not zero, not excessively slow)."""
        from src.indexing.embedder import _INTER_BATCH_DELAY
        assert 0.1 <= _INTER_BATCH_DELAY <= 2.0
