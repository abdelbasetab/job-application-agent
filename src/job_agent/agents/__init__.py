"""Agents used by the application pipeline.

Profiler structures candidate evidence, Scout obtains source-validated jobs,
Matcher scores them, Writer drafts evidence-bound applications, and Tracker
persists state. Deterministic paths remain available when optional LLM calls
are disabled or fail.
"""
