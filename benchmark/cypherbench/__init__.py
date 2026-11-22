"""CypherBench (Feng et al., 2024; arXiv:2412.18702) evaluation for GQL-Core.

Data: https://huggingface.co/datasets/megagonlabs/cypherbench (Apache-2.0).
Official code: https://github.com/megagonlabs/cypherbench (Apache-2.0).

Two layers:
  Layer A (engine): run every *gold* Cypher query on GQL-Core and compare the
      result with the gold answer CypherBench computed on Neo4j (``answer_json``).
  Layer B (NL->Cypher): a local Ollama model translates the question with the
      official zero-shot prompt; the predicted query runs on GQL-Core and is
      scored with the official execution-accuracy metric against the gold answer.
"""
