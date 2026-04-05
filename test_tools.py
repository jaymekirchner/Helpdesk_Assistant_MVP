"""
Unit tests for the three MCP-backed tool functions in appFinal.py:
  - lookup_user
  - check_device_status
  - create_ticket

Run with:  python -m pytest test_tools.py -v
       or: python -m unittest test_tools -v
"""

import json
import sys
import unittest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Lightweight stand-ins for the fastmcp CallToolResult shape that
# _extract_mcp_records() expects: result.content[i].text == JSON string
# ---------------------------------------------------------------------------

class _Content:
    def __init__(self, payload: dict):
        self.text = json.dumps(payload)


class _Result:
    def __init__(self, payload: dict):
        self.content = [_Content(payload)]


def _ok(data: dict) -> _Result:
    return _Result({"success": True, "data": data})


def _err(message: str) -> _Result:
    return _Result({"success": False, "error": message})


# ---------------------------------------------------------------------------
# Import appFinal — env vars will be absent so agents stay None,
# but the tool functions (_call_mcp_tool wrappers) are always defined.
# ---------------------------------------------------------------------------
import appFinal  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════
# lookup_user  (5 tests, 1 edge case)
# ═══════════════════════════════════════════════════════════════════════════

class TestLookupUser(unittest.TestCase):

    @patch("appFinal._call_mcp_tool")
    def test_successful_lookup_by_username(self, mock_call):
        """Happy path: lookup by username — all profile fields returned correctly."""
        mock_call.return_value = _ok({
            "username": "jane.doe",
            "first_name": "Jane",
            "last_name": "Doe",
            "department": "Engineering",
            "email": "jane.doe@company.com",
            "device_id": "LAPTOP-1001",
        })
        result = appFinal.lookup_user(username="jane.doe")
        self.assertIn("jane.doe", result)
        self.assertIn("Jane Doe", result)
        self.assertIn("Engineering", result)
        self.assertIn("jane.doe@company.com", result)
        self.assertIn("LAPTOP-1001", result)
        forwarded = mock_call.call_args[0][1]
        self.assertEqual(forwarded, {"username": "jane.doe"})

    @patch("appFinal._call_mcp_tool")
    def test_successful_lookup_by_first_and_last_name(self, mock_call):
        """Happy path: lookup by first_name + last_name when username is unknown."""
        mock_call.return_value = _ok({
            "username": "jsmith",
            "first_name": "John",
            "last_name": "Smith",
            "department": "IT",
            "email": "jsmith@company.com",
            "device_id": "LAPTOP-2002",
        })
        result = appFinal.lookup_user(first_name="John", last_name="Smith")
        self.assertIn("John Smith", result)
        self.assertIn("jsmith", result)
        forwarded = mock_call.call_args[0][1]
        self.assertEqual(forwarded, {"first_name": "John", "last_name": "Smith"})

    @patch("appFinal._call_mcp_tool")
    def test_falls_back_to_name_field_when_parts_absent(self, mock_call):
        """When first_name/last_name are missing from DB response, 'name' field is used."""
        mock_call.return_value = _ok({
            "username": "jsmith",
            "name": "John Smith",
            "department": "IT",
            "email": "jsmith@company.com",
            "device_id": "LAPTOP-2002",
        })
        result = appFinal.lookup_user(username="jsmith")
        self.assertIn("John Smith", result)

    @patch("appFinal._call_mcp_tool")
    def test_user_not_found_returns_error_message(self, mock_call):
        """success=False envelope returns the error string to the caller."""
        mock_call.return_value = _err("No user found for username 'ghost.user'.")
        result = appFinal.lookup_user(username="ghost.user")
        self.assertIn("No user found", result)

    @patch("appFinal._call_mcp_tool")
    def test_mcp_exception_is_caught_and_reported(self, mock_call):
        """Network failure is caught and a friendly error string is returned."""
        mock_call.side_effect = ConnectionError("MCP server unreachable")
        result = appFinal.lookup_user(username="jane.doe")
        self.assertIn("Error looking up user via MCP", result)
        self.assertIn("MCP server unreachable", result)

    def test_edge_case_no_args_returns_guidance_message(self):
        """Edge case: calling with no username and no name returns a helpful message without hitting MCP."""
        result = appFinal.lookup_user()
        self.assertIn("username", result.lower())
        self.assertIn("first name", result.lower())


# ═══════════════════════════════════════════════════════════════════════════
# check_device_status  (5 tests, 1 edge case)
# ═══════════════════════════════════════════════════════════════════════════

class TestCheckDeviceStatus(unittest.TestCase):

    @patch("appFinal._call_mcp_tool")
    def test_successful_lookup_by_device_id(self, mock_call):
        """Happy path: device looked up by explicit device ID."""
        mock_call.return_value = _ok({
            "device_id": "LAPTOP-1001",
            "username": "jane.doe",
            "status": "Online",
            "vpn_client": "Cisco AnyConnect",
            "last_seen": "2026-04-04T10:00:00Z",
        })
        result = appFinal.check_device_status("LAPTOP-1001")
        self.assertIn("LAPTOP-1001", result)
        self.assertIn("Online", result)
        self.assertIn("Cisco AnyConnect", result)

    @patch("appFinal._call_mcp_tool")
    def test_successful_lookup_by_username(self, mock_call):
        """Device record resolved via username rather than device ID."""
        mock_call.return_value = _ok({
            "device_id": "LAPTOP-2002",
            "username": "bob.smith",
            "status": "Offline",
            "vpn_client": "GlobalProtect",
            "last_seen": "2026-04-03T08:30:00Z",
        })
        result = appFinal.check_device_status("bob.smith")
        self.assertIn("bob.smith", result)
        self.assertIn("Offline", result)
        self.assertIn("LAPTOP-2002", result)

    @patch("appFinal._call_mcp_tool")
    def test_device_not_found_returns_error_message(self, mock_call):
        """success=False returns the error message string."""
        mock_call.return_value = _err("Device not found")
        result = appFinal.check_device_status("LAPTOP-9999")
        self.assertIn("Device not found", result)

    @patch("appFinal._call_mcp_tool")
    def test_mcp_exception_is_caught_and_reported(self, mock_call):
        """Timeout or network error is caught and returned as a readable string."""
        mock_call.side_effect = TimeoutError("Connection timed out")
        result = appFinal.check_device_status("LAPTOP-1001")
        self.assertIn("Error checking device status via MCP", result)
        self.assertIn("Connection timed out", result)

    @patch("appFinal._call_mcp_tool")
    def test_edge_case_empty_string_identifier(self, mock_call):
        """Edge case: empty string is forwarded unchanged; MCP error is propagated gracefully."""
        mock_call.return_value = _err("Invalid device or username")
        result = appFinal.check_device_status("")
        forwarded = mock_call.call_args[0][1]["device_or_username"]
        self.assertEqual(forwarded, "")
        self.assertIn("Invalid device or username", result)


# ═══════════════════════════════════════════════════════════════════════════
# create_ticket  (5 tests, 1 edge case)
# ═══════════════════════════════════════════════════════════════════════════

class TestCreateTicket(unittest.TestCase):

    @patch("appFinal._call_mcp_tool")
    def test_successful_ticket_creation_all_fields(self, mock_call):
        """Happy path: ticket created with every field explicitly supplied."""
        mock_call.return_value = _ok({
            "ticket_id": "TKT-0042",
            "status": "Open",
            "priority": "High",
            "assignment_group": "Network Team",
        })
        result = appFinal.create_ticket(
            issue="VPN not connecting on Windows 11",
            user="jane.doe",
            category="VPN",
            severity="High",
            impacted_system="Cisco AnyConnect",
        )
        self.assertIn("TKT-0042", result)
        self.assertIn("Open", result)
        self.assertIn("Network Team", result)

    @patch("appFinal._call_mcp_tool")
    def test_ticket_creation_with_default_values(self, mock_call):
        """Only issue is required; omitted params must default and be forwarded correctly."""
        mock_call.return_value = _ok({
            "ticket_id": "TKT-0099",
            "status": "Open",
            "priority": "Medium",
            "assignment_group": "General IT",
        })
        appFinal.create_ticket(issue="Unspecified IT issue")
        payload = mock_call.call_args[0][1]
        self.assertEqual(payload["user"], "unknown")
        self.assertEqual(payload["category"], "General")
        self.assertEqual(payload["severity"], "Medium")
        self.assertEqual(payload["impacted_system"], "Unknown")

    @patch("appFinal._call_mcp_tool")
    def test_ticket_creation_fails_with_error(self, mock_call):
        """success=False returns a 'Ticket creation failed' message with the error detail."""
        mock_call.return_value = _err("Freshworks API unavailable")
        result = appFinal.create_ticket(issue="Outlook crash")
        self.assertIn("Ticket creation failed", result)
        self.assertIn("Freshworks API unavailable", result)

    @patch("appFinal._call_mcp_tool")
    def test_mcp_exception_is_caught_and_reported(self, mock_call):
        """Unexpected runtime errors from _call_mcp_tool return a readable error string."""
        mock_call.side_effect = RuntimeError("Unexpected MCP error")
        result = appFinal.create_ticket(issue="Email not loading")
        self.assertIn("Error calling MCP ticket tool", result)
        self.assertIn("Unexpected MCP error", result)

    @patch("appFinal._call_mcp_tool")
    def test_edge_case_very_long_issue_string(self, mock_call):
        """Edge case: issue strings >500 chars are forwarded without truncation."""
        long_issue = "Outlook crashes when opening attachment " * 20  # ~780 chars
        mock_call.return_value = _ok({
            "ticket_id": "TKT-0200",
            "status": "Open",
            "priority": "Low",
            "assignment_group": "Email Team",
        })
        appFinal.create_ticket(issue=long_issue)
        forwarded_issue = mock_call.call_args[0][1]["issue"]
        self.assertEqual(forwarded_issue, long_issue)


if __name__ == "__main__":
    unittest.main()
