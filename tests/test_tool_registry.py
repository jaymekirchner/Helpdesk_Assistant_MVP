"""
Unit tests for all MCP-backed tool functions in agents/tool_registry.py:
  - lookup_user
  - check_device_status
  - lookup_ticket
  - lookup_tickets_by_user
  - create_ticket

Run with:  python -m unittest tests/test_tool_registry.py -v
"""

import unittest
from unittest.mock import patch
import json

# Import the tool functions directly
from agents import tool_registry

# Helper mocks for MCP client responses
class _Content:
    def __init__(self, payload: dict):
        self.text = json.dumps(payload)

class _Result:
    def __init__(self, payload: dict):
        self.content = [_Content(payload)]

def _ok(data: dict):
    return _Result({"success": True, "data": data})

def _err(message: str):
    return _Result({"success": False, "error": message})

class TestLookupUser(unittest.TestCase):
    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_lookup_by_username(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": True, "data": [{"username": "john.doe", "first_name": "John", "last_name": "Doe"}]}]
        result = tool_registry.lookup_user(username="john.doe")
        self.assertIn("john.doe", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_lookup_by_name(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": True, "data": [{"username": "jane.smith", "first_name": "Jane", "last_name": "Smith"}]}]
        result = tool_registry.lookup_user(first_name="Jane", last_name="Smith")
        self.assertIn("Jane Smith", result)

    def test_no_args(self):
        result = tool_registry.lookup_user()
        self.assertIn("username", result.lower())

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_multiple_users(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": True, "data": [
            {"username": "alex.lee", "first_name": "Alex", "last_name": "Lee"},
            {"username": "alex.lee2", "first_name": "Alex", "last_name": "Lee"}
        ], "count": 2}]
        result = tool_registry.lookup_user(first_name="Alex", last_name="Lee")
        self.assertIn("2 users found", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_user_not_found(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": False, "error": "No user found"}]
        result = tool_registry.lookup_user(username="ghost.user")
        self.assertIn("No user found", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_special_characters_username(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": False, "error": "Invalid username"}]
        result = tool_registry.lookup_user(username="john!@#")
        self.assertIn("Invalid username", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_only_first_name(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": False, "error": "Please provide both first and last name"}]
        result = tool_registry.lookup_user(first_name="John")
        self.assertIn("first name", result.lower())


class TestCheckDeviceStatus(unittest.TestCase):
    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_by_device_id(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": True, "data": {"device_id": "LAPTOP-1001", "username": "john.doe", "status": "Online", "vpn_client": "Cisco", "last_seen": "2026-04-04T10:00:00Z"}}]
        result = tool_registry.check_device_status(device_or_username="LAPTOP-1001")
        self.assertIn("LAPTOP-1001", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_by_username(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": True, "data": {"device_id": "LAPTOP-2002", "username": "jane.smith", "status": "Offline", "vpn_client": "GlobalProtect", "last_seen": "2026-04-03T08:30:00Z"}}]
        result = tool_registry.check_device_status(device_or_username="jane.smith")
        self.assertIn("jane.smith", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_by_name(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": True, "data": {"device_id": "LAPTOP-3003", "username": "alex.lee", "status": "Online", "vpn_client": "AnyConnect", "last_seen": "2026-04-02T09:00:00Z"}}]
        result = tool_registry.check_device_status(first_name="Alex", last_name="Lee")
        self.assertIn("alex.lee", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_device_not_found(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": False, "error": "Device not found"}]
        result = tool_registry.check_device_status(device_or_username="UNKNOWN-DEVICE")
        self.assertIn("Device not found", result)

    def test_missing_all_fields(self):
        result = tool_registry.check_device_status()
        self.assertTrue("Unknown" in result or "Device status" in result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_only_first_name(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": False, "error": "Please provide both first and last name"}]
        result = tool_registry.check_device_status(first_name="John")
        self.assertIn("first name", result.lower())

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_special_characters_device_id(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": False, "error": "Invalid device or username"}]
        result = tool_registry.check_device_status(device_or_username="LAPTOP-!@#")
        self.assertIn("Invalid device", result)

class TestLookupTicket(unittest.TestCase):
    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_valid_ticket_id(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": True, "data": {"ticket_id": "TICK-12345", "subject": "VPN Issue", "status": "Open", "first_name": "John", "last_name": "Doe"}}]
        result = tool_registry.lookup_ticket(ticket_id="TICK-12345")
        self.assertIn("TICK-12345", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_nonexistent_ticket_id(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": False, "error": "Ticket lookup failed"}]
        result = tool_registry.lookup_ticket(ticket_id="TICK-00000")
        self.assertIn("Ticket lookup failed", result)

    def test_empty_ticket_id(self):
        result = tool_registry.lookup_ticket(ticket_id="")
        self.assertTrue("Unknown" in result or "Ticket details" in result or "failed" in result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_special_characters_ticket_id(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": False, "error": "Invalid ticket ID"}]
        result = tool_registry.lookup_ticket(ticket_id="TICK-!@#")
        self.assertIn("Invalid ticket", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_ticket_id_as_integer(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": False, "error": "Ticket lookup failed"}]
        result = tool_registry.lookup_ticket(ticket_id=12345)
        self.assertIn("failed", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_ticket_id_with_spaces(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": True, "data": {"ticket_id": "TICK-12345", "subject": "VPN Issue", "status": "Open", "first_name": "John", "last_name": "Doe"}}]
        result = tool_registry.lookup_ticket(ticket_id="  TICK-12345  ")
        self.assertIn("TICK-12345", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_closed_ticket(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": True, "data": {"ticket_id": "TICK-54321", "subject": "Old Issue", "status": "Closed", "first_name": "Jane", "last_name": "Smith"}}]
        result = tool_registry.lookup_ticket(ticket_id="TICK-54321")
        self.assertIn("Closed", result)

class TestLookupTicketsByUser(unittest.TestCase):
    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_by_username(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": True, "data": [{"ticket_id": "TICK-1", "first_name": "John", "last_name": "Doe"}]}]
        result = tool_registry.lookup_tickets_by_user(username="john.doe")
        self.assertIn("Found", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_by_name(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": True, "data": [{"ticket_id": "TICK-2", "first_name": "Jane", "last_name": "Smith"}]}]
        result = tool_registry.lookup_tickets_by_user(first_name="Jane", last_name="Smith")
        self.assertIn("Found", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_no_tickets(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": True, "data": []}]
        result = tool_registry.lookup_tickets_by_user(username="no.tickets")
        self.assertIn("No tickets found", result)

    def test_missing_all_fields(self):
        result = tool_registry.lookup_tickets_by_user()
        self.assertTrue("user" in result.lower() or "error" in result.lower() or "found" in result.lower())

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_only_first_name(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": False, "error": "Please provide both first and last name"}]
        result = tool_registry.lookup_tickets_by_user(first_name="John")
        self.assertIn("first name", result.lower())

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_special_characters_username(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": False, "error": "Invalid username"}]
        result = tool_registry.lookup_tickets_by_user(username="john!@#")
        self.assertIn("Invalid username", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_many_tickets(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": True, "data": [
            {"ticket_id": f"TICK-{i}", "first_name": "Power", "last_name": "User"} for i in range(10)
        ]}]
        result = tool_registry.lookup_tickets_by_user(username="power.user")
        self.assertIn("Found", result)

class TestCreateTicket(unittest.TestCase):
    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_all_fields(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": True, "data": {"ticket_id": "TKT-0042", "status": "Open", "assignment_group": "Network Team"}}]
        result = tool_registry.create_ticket(
            issue="VPN not connecting on Windows 11",
            user="jane.doe",
            category="VPN",
            severity="High",
            impacted_system="Cisco AnyConnect",
        )
        self.assertIn("TKT-0042", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_minimal_fields(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": True, "data": {"ticket_id": "TKT-0099", "status": "Open", "assignment_group": "General IT"}}]
        result = tool_registry.create_ticket(issue="Unspecified IT issue")
        self.assertIn("TKT-0099", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_missing_issue(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": False, "error": "Missing issue"}]
        result = tool_registry.create_ticket(issue="")
        self.assertIn("Missing issue", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_invalid_severity(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": False, "error": "Invalid severity"}]
        result = tool_registry.create_ticket(issue="VPN down", severity="SuperCritical")
        self.assertIn("Invalid severity", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_special_characters_user(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": False, "error": "Invalid user"}]
        result = tool_registry.create_ticket(issue="Printer jam", user="john!@#")
        self.assertIn("Invalid user", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_additional_cc_emails(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": True, "data": {"ticket_id": "TKT-0100", "status": "Open"}}]
        result = tool_registry.create_ticket(issue="Printer jam", additional_cc_emails=["boss@company.com"])
        self.assertIn("TKT-0100", result)

    @patch("agents.tool_registry.mcp_client.call_tool")
    @patch("agents.tool_registry.mcp_client.extract_records")
    def test_non_english_language(self, mock_extract, mock_call):
        mock_call.return_value = None
        mock_extract.return_value = [{"success": True, "data": {"ticket_id": "TKT-0200", "status": "Open"}}]
        result = tool_registry.create_ticket(issue="No puedo acceder a la VPN", source_language="Spanish")
        self.assertIn("TKT-0200", result)

if __name__ == "__main__":
    unittest.main()
