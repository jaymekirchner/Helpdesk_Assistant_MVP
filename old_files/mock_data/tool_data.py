
class Tools:
   # ============================================================
# MOCK TOOL DATA
# ============================================================
    MOCK_USERS = {
        "jdoe": {
            "username": "jdoe",
            "name": "John Doe",
            "department": "Finance",
            "email": "jdoe@company.com",
            "device_id": "LAPTOP-1001",
        },
        "asmith": {
            "username": "asmith",
            "name": "Alice Smith",
            "department": "HR",
            "email": "asmith@company.com",
            "device_id": "LAPTOP-1002",
        },
    }
    
    MOCK_DEVICES = {
        "LAPTOP-1001": {
            "device_id": "LAPTOP-1001",
            "status": "online",
            "vpn_client": "installed",
            "last_seen": "2026-03-31 08:15",
        },
        "LAPTOP-1002": {
            "device_id": "LAPTOP-1002",
            "status": "offline",
            "vpn_client": "unknown",
            "last_seen": "2026-03-30 19:42",
        },
    }
    