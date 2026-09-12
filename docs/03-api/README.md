# API Reference

Contracts for the system's interfaces: the backend ABCs third-party backends
implement, the queue/storage payload wire format, and the public import
surface. Signatures and semantics here are verified against
`src/scrapy_extension/`.

## Contents

| Document | Description |
| -------- | ----------- |
| [Backend Interfaces](backend-interfaces.md) | Contracts for `Backend`, `QueueBackend`, `SetBackend`, and `StorageBackend` |
| [JSON Codec](json-codec.md) | Wire contract for `Serializer` / `JSONSerializer` queue and storage payloads |
| [Package Surface](package-surface.md) | Public exports, lazy imports, the backend registry, and the error hierarchy |

## What belongs here

- API contracts and reference (OpenAPI, protobuf, JSON Schema, GraphQL SDL)
- Schema definitions and migration notes
- Versioning and compatibility policy

Contracts published here are the source of truth; implementations are
verified against them. Interface changes still under discussion belong in
[00-rfcs/](../00-rfcs/).
