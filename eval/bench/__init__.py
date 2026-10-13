"""Public long-memory benchmarks against a running Mem OS: LoCoMo and LongMemEval.

See eval/bench/README.md. The pipeline is the one every memory product is
measured with -- ingest conversations, let the service extract, search per
question, answer from what search returned, judge the answer -- so a number
here is comparable in kind with published ones, and MemScore reports accuracy
together with the latency and context tokens it cost.
"""
