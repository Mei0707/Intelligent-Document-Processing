# Recorded benchmark baseline

Run date: 2026-10-23. This is a synthetic development set of eight documents and eleven questions, not a production quality or capacity claim. The cold run includes two repetitions per question/strategy, one embedding setup, and eight classification/extraction examples. The warm run repeats eleven questions three times with the application cache enabled. All provider/schema error counts were zero.

Chat model: `gpt-4o-mini`; embeddings: `text-embedding-3-small`; K=3 passages. Both runs use the dataset hash recorded in their JSON reports. Cost estimates use the configurable rates captured in each report; setup/extraction costs are separate from per-query costs.

| Strategy | Recall@3 | MRR@3 | Labeled answer correctness | Answer p50 | Answer p95 | Est. USD/query |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| bm25 | 100% | 1.00 | 100.0% | 1.27s | 1.69s | $0.0001055 |
| vector | 100% | 1.00 | 100.0% | 1.68s | 2.49s | $0.0001090 |
| hybrid | 100% | 1.00 | 100.0% | 1.56s | 1.88s | $0.0001089 |
| hybrid_rerank | 100% | 1.00 | 95.5% | 2.51s | 2.96s | $0.0002121 |

Classification and expected-field accuracy were both 100% on the eight extraction examples. These labels cover a subset of expected fields, not every possible output field.

Hybrid is the default because this baseline showed lower cost and latency than reranking with no lost labeled recall. Reranking remains available for collections that benefit from it. The set is too small and lexical to establish which strategy will generalize best.

| Cached hybrid + reranking trial | p50 | p95 | Provider calls | Est. USD |
| --- | ---: | ---: | ---: | ---: |
| 1 | 2425.51ms | 2954.26ms | 32 | $0.0023221 |
| 2 | 6.46ms | 8.51ms | 0 | $0.0000000 |
| 3 | 4.48ms | 6.50ms | 0 | $0.0000000 |

These cache measurements exclude corpus setup and HTTP transport. Later trials reuse exact prompts/results; real-world cache hit rates depend on repeated queries and document changes. Cached responses preserve the original answer quality, including mistakes. Provider-managed cached-input tokens were zero in these particular runs; the measured speedup comes from the application response cache.

Artifacts: [cold/live report](benchmarks/live.json), [cache report](benchmarks/warm.json), [offline smoke report](benchmarks/offline.json). Scoring and limitations are described in [architecture](architecture.md).
