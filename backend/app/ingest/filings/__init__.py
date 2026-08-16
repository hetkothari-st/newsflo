"""TASK 1.3 -- the filing extraction pipeline.

    acquire.py       Stage A -- fetch and STORE the raw artefact (never discard)
    documents.py     the text layer: pypdf / plain text -> SourceDocument
    xbrl.py          Stage B -- XBRL instance parsing (stdlib xml only)
    deterministic.py Stage B -- segment note / P&L lines -> ledger loaders
    llm_extract.py   Stage C -- unstructured content, INJECTED client only
    verbatim.py      the anti-hallucination gate for the ledger itself
    proposals.py     Stage D -- proposals land as PENDING_REVIEW

NOTHING IN THIS PACKAGE WRITES `company_exposure`. Extraction proposes;
`app.ledger.review` (a human) writes. That is enforced by a database trigger
and by tests/phase1/test_no_direct_write.py, which ast-scans this package.
"""
