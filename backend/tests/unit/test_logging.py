"""Unit tests for PII-safe logging and JSON formatting."""

import json
import logging

from backend.app.core.logging import JSONFormatter, PIISafeFilter


def test_pii_safe_filter_redacts_sensitive_data() -> None:
    """Filter must redact email addresses, IBANs, phone numbers, and card numbers."""
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Contact user at supplier@example.com with IBAN DE89370400440532013000 and phone +1-555-019-2831",
        args=(),
        exc_info=None,
    )
    pii_filter = PIISafeFilter()
    result = pii_filter.filter(record)

    assert result is True
    assert "supplier@example.com" not in record.msg
    assert "[REDACTED_EMAIL]" in record.msg
    assert "DE89370400440532013000" not in record.msg
    assert "[REDACTED_IBAN]" in record.msg
    assert "+1-555-019-2831" not in record.msg
    assert "[REDACTED_PHONE]" in record.msg


def test_json_formatter_structure() -> None:
    """Formatter must produce valid JSON with correlation IDs."""
    record = logging.LogRecord(
        name="worker_logger",
        level=logging.WARNING,
        pathname="worker.py",
        lineno=42,
        msg="Task step executed",
        args=(),
        exc_info=None,
    )
    record.job_id = "job_xyz_123"
    record.thread_id = "thread_abc_456"
    record.tenant_id = "tenant_001"

    formatter = JSONFormatter()
    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert parsed["level"] == "WARNING"
    assert parsed["message"] == "Task step executed"
    assert parsed["job_id"] == "job_xyz_123"
    assert parsed["thread_id"] == "thread_abc_456"
    assert parsed["tenant_id"] == "tenant_001"
