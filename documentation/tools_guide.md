# IT Helpdesk MCP Server — Tools Guide

This guide summarizes each tool exposed by `mcp_server.py`. All tools return a consistent envelope:

```json
{
  "success": true | false,
  "error": null | "<error message>",
  "data": { ... }
}
```

---

## 1. `health_check`

**Purpose:** Verifies that the MCP server and its dependencies are reachable and configured.

**Parameters:** _None_

**What it checks:**
| Dependency | Condition |
|---|---|
| PostgreSQL | Runs `SELECT 1` against the configured connection string |
| Freshworks | Checks that `FRESHWORKS_API_KEY` and `FRESHWORKS_DOMAIN` env vars are set |

**Return (`data`):**
| Field | Type | Description |
|---|---|---|
| `status` | string | `"ready"` (all checks pass) or `"degraded"` |
| `checks` | object | Per-dependency result: `"ok"`, `"configured"`, or `"error: <msg>"` |
| `timestamp_utc` | string | ISO-8601 timestamp of the check |

**Example use case:** Call before processing requests to confirm all external systems are available.

---

## 2. `create_ticket`

**Purpose:** Creates a new IT support ticket in Freshworks and mirrors it to the `demo.tickets` PostgreSQL table.

**Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `issue` | string | Yes | — | Description of the problem (truncated to 100 chars for subject) |
| `user` | string | No | `"unknown"` | Username or email of the requester |
| `category` | string | No | `"General"` | Topic area. One of: `VPN`, `Email`, `MFA`, `Device`, `Account`, `Software`, `Hardware`, `General` |
| `severity` | string | No | `"Medium"` | `Low`, `Medium`, `High`, or `Critical` |
| `impacted_system` | string | No | `"Unknown"` | System or asset affected |
| `first_name` | string | No | `""` | Used to resolve the user record when `user` is not a match |
| `last_name` | string | No | `""` | Used alongside `first_name` for user resolution |

**Severity → Priority mapping:**
| Severity | Freshworks Priority | Urgency / Impact |
|---|---|---|
| Low | 1 | 1 |
| Medium | 2 | 2 |
| High | 3 | 3 |
| Critical | 4 | 3 |

**Return (`data`):**
| Field | Description |
|---|---|
| `ticket_id` | Freshworks internal ID |
| `ticket_number` | Human-readable ticket number |
| `user` | Requester identifier as supplied |
| `issue` | Original issue text |
| `category` | Resolved category |
| `severity` | Resolved severity |
| `impacted_system` | Impacted system as supplied |
| `status` | Mapped status string (e.g., `"Open"`) |
| `priority` | Integer priority (1–4) |
| `assignment_group` | Freshworks group ID |
| `created_at_utc` | Ticket creation timestamp |
| `url` | Direct link to the ticket in Freshworks |

**Notes:**
- Postgres persistence is non-fatal; ticket creation succeeds even if the DB write fails.
- If `user` contains `@`, it is used as the requester email directly; otherwise the default requester email (`FRESHWORKS_DEFAULT_REQUESTER_EMAIL`) is used.

---

## 3. `lookup_user`

**Purpose:** Retrieves a corporate user's profile from `demo.users` in PostgreSQL.

**Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `username` | string | Conditionally | Exact username (case-insensitive) |
| `first_name` | string | Conditionally | First name (used with `last_name`) |
| `last_name` | string | Conditionally | Last name (used with `first_name`) |

> At least one of `username` **or** (`first_name` + `last_name`) must be provided.

**Return (`data`):**
| Field | Description |
|---|---|
| `username` | Login username |
| `first_name` | User's first name |
| `last_name` | User's last name |
| `department` | Department the user belongs to |
| `email` | Corporate email address |
| `device_id` | ID of the device assigned to the user |

When searching by name, multiple matches may be returned as an array under `data`, along with a `count` field.

---

## 4. `lookup_ticket`

**Purpose:** Retrieves full details for a single ticket by its ID, including the requester's contact information.

**Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `ticket_id` | string | Yes | The exact ticket ID to look up |

**Return (`data`):**
| Field | Description |
|---|---|
| `ticket_id` | Ticket identifier |
| `severity` | Severity level |
| `status` | Current status (e.g., `"Open"`, `"Resolved"`) |
| `assignment_group` | Assigned support group |
| `category` | Issue category |
| `created_at` | Ticket creation timestamp |
| `subject` | Ticket subject line |
| `description_text` | Full issue description |
| `ticket_type` | `"Incident"` or `"Service Request"` |
| `first_name` | Requester's first name (from joined `demo.users`) |
| `last_name` | Requester's last name |
| `email` | Requester's email |

---

## 5. `lookup_tickets_by_user`

**Purpose:** Returns all support tickets associated with a given user, ordered newest first.

**Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `username` | string | Conditionally | Exact username |
| `first_name` | string | Conditionally | First name (used with `last_name`) |
| `last_name` | string | Conditionally | Last name (used with `first_name`) |

> At least one of `username` **or** (`first_name` + `last_name`) must be provided. Both can be supplied; the query uses `OR` to include results from either match.

**Return (`data`):** Array of ticket objects, each containing:
| Field | Description |
|---|---|
| `ticket_id` | Ticket identifier |
| `severity` | Severity level |
| `status` | Current ticket status |
| `assignment_group` | Assigned group |
| `category` | Issue category |
| `created_at` | Creation timestamp |
| `subject` | Ticket subject |
| `description_text` | Issue description |
| `ticket_type` | `"Incident"` or `"Service Request"` |
| `first_name` | Requester first name |
| `last_name` | Requester last name |
| `email` | Requester email |
| `username` | Resolved username |

---

## 6. `check_device_status`

**Purpose:** Returns the current status of a device, including VPN client installation and last-seen timestamp.

**Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `device_or_username` | string | Conditionally | A device ID (e.g., `LAPTOP-1001`) **or** a username |
| `first_name` | string | Conditionally | First name (used with `last_name`) |
| `last_name` | string | Conditionally | Last name (used with `first_name`) |

> At least one of `device_or_username` **or** (`first_name` + `last_name`) must be provided. All three can be supplied; the query uses `OR` across all conditions.

The tool searches `demo.devices` joined with `demo.users` and matches on device ID, username, or full name (all case-insensitive).

**Return (`data`):**
| Field | Description |
|---|---|
| `device_id` | Device identifier |
| `status` | Connection state (e.g., `"online"`, `"offline"`) |
| `vpn_client` | VPN client state (e.g., `"installed"`, `"unknown"`) |
| `last_seen` | Last activity timestamp |
| `username` | Username of the assigned user (`"unknown"` if unassigned) |
| `first_name` | First name of the assigned user (empty string if unassigned) |
| `last_name` | Last name of the assigned user (empty string if unassigned) |

---

## Environment Variables Reference

| Variable | Used By | Description |
|---|---|---|
| `AZURE_POSTGRESQL_CONNECTION_STRING` | All DB tools | Full Postgres connection string (preferred) |
| `AZURE_POSTGRESQL_USER` | All DB tools | Postgres username (fallback) |
| `AZURE_POSTGRESQL_PASSWORD` | All DB tools | Postgres password (fallback) |
| `AZURE_POSTGRESQL_HOST` | All DB tools | Postgres host (fallback) |
| `AZURE_POSTGRESQL_PORT` | All DB tools | Postgres port, default `5432` (fallback) |
| `AZURE_POSTGRESQL_DBNAME` | All DB tools | Database name, default `postgres` (fallback) |
| `FRESHWORKS_API_KEY` | `create_ticket`, `health_check` | Freshworks API key |
| `FRESHWORKS_DOMAIN` | `create_ticket`, `health_check` | Freshworks subdomain or full host |
| `FRESHWORKS_DEFAULT_REQUESTER_EMAIL` | `create_ticket` | Fallback email when user has no `@` address |
| `MCP_BIND_HOST` | Server startup | HTTP bind host, default `127.0.0.1` |
| `MCP_PORT` | Server startup | HTTP port, default `8000` |

---

## Running the Server

```bash
# STDIO transport (default — compatible with MCP Inspector)
python mcp_server.py

# HTTP transport
python mcp_server.py --http

# HTTP transport via FastMCP CLI
fastmcp run mcp_server.py:mcp --transport http --port 8000

# Inspect tools interactively
npx @modelcontextprotocol/inspector python mcp_server.py
```
