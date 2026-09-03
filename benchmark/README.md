# Benchmark

This directory will contain the myRAG evaluation dataset and the benchmark-driven regression suite.

## Directory structure

```
benchmark/
├── documents/    Source documents used in evaluation
├── questions/    Evaluation question sets
├── gold/         Gold-standard (expected) answers
├── results/      Benchmark run outputs and metrics
└── README.md
```

## Purpose

The benchmark is the regression gate for the RAG system. Every change to the RAG engine must be evaluated against this dataset before merging.

## Not yet populated

Benchmark data will be added when the first RAG components are built.
