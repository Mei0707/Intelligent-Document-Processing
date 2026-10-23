from contextlib import nullcontext
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch, MagicMock
import fakeredis
from app.config import settings
from app.services import llm


def response(content='{"ok": true}', finish="stop", inp=100, out=20, cached=40):
    return NS(choices=[NS(message=NS(content=content), finish_reason=finish)],
              usage=NS(prompt_tokens=inp, completion_tokens=out, prompt_tokens_details=NS(cached_tokens=cached)))


class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.client = MagicMock()
        self.client.chat.completions.create.return_value = response()
        self.patches = [patch("app.services.llm.redis_client", return_value=self.redis),
                        patch("app.services.llm._client", return_value=self.client),
                        patch.object(settings, "cache_ttl_seconds", 60),
                        patch.object(settings, "llm_concurrency", 1),
                        patch.object(settings, "model_prices", {
                            settings.openai_chat_model: {"input": 1, "output": 2, "cached_input": .5},
                            settings.openai_embedding_model: {"input": .02},
                        })]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def test_response_cache_and_actual_cached_provider_token_cost(self):
        with llm.measure_usage() as usage:
            self.assertEqual(llm.chat_json("Return JSON", "test"), {"ok": True})
            self.assertEqual(llm.chat_json("Return JSON", "test"), {"ok": True})
        self.assertEqual(self.client.chat.completions.create.call_count, 1)
        self.assertEqual(usage.calls, 1)
        self.assertEqual(usage.response_cache_hits, 1)
        self.assertEqual(usage.cached_tokens, 40)
        self.assertAlmostEqual(usage.estimated_cost_usd, .00012)
        self.assertEqual(self.redis.zcard("idp:llm:permits"), 0)

    def test_global_concurrency_permit_released_on_exception(self):
        with llm.inference_slot():
            with self.assertRaises(RuntimeError):
                with llm.inference_slot():
                    pass
        self.assertEqual(self.redis.zcard("idp:llm:permits"), 0)
        with self.assertRaises(ValueError):
            with llm.inference_slot():
                raise ValueError("test")
        self.assertEqual(self.redis.zcard("idp:llm:permits"), 0)

    def test_routing_cache_key_is_model_specific_and_prompt_budget_enforced(self):
        with patch.object(settings, "complex_model", "quality-model"):
            with llm.measure_usage("high") as usage:
                llm.chat_json("Return JSON", "test", task="answer")
            self.assertEqual(self.client.chat.completions.create.call_args.kwargs["model"], "quality-model")
            self.assertIsNone(usage.to_dict()["estimated_cost_usd"])
        with patch.object(settings, "llm_input_tokens", 10):
            with self.assertRaises(ValueError):
                llm.chat_json("instructions exceed the budget", "question")

    def test_embedding_batches_and_response_order(self):
        def create(**kwargs):
            batch = kwargs["input"]
            return NS(data=[NS(index=i, embedding=[float(i), 1.]) for i in reversed(range(len(batch)))],
                      usage=NS(prompt_tokens=10))
        self.client.embeddings.create.side_effect = create
        with patch.object(settings, "embedding_batch_size", 2), llm.measure_usage() as usage:
            result = llm.embed(["one", "two", "three"])
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0], [0., 1.])
        self.assertEqual(result[1], [1., 1.])
        self.assertEqual(usage.calls, 2)
        with self.assertRaises(ValueError):
            llm.embed([""])

    def test_truncated_model_output_is_counted_and_never_cached(self):
        self.client.chat.completions.create.return_value = response('{"ok":', finish="length")
        with llm.measure_usage() as usage:
            with self.assertRaises(ValueError):
                llm.chat_json("Return JSON", "test")
        self.assertEqual(usage.calls, 1)
        self.assertEqual(len(self.redis.keys("idp:inference:*")), 0)


if __name__ == "__main__":
    unittest.main()
