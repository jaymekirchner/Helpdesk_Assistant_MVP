
# Entity Relationship Diagram — `demo` Schema

```mermaid

    USERS {
        int4    user_id       PK  "IDENTITY, NOT NULL"
        varchar last_name
        varchar first_name
        varchar username
        varchar department
        varchar email
        varchar device_id     UK  "unique — primary device (denormalized)"
    }

    DEVICES {
        varchar   device_id    PK  "NOT NULL"
        varchar   device_type
        varchar   vpn_client
        varchar   status           "default 'Active'"
        int4      user_id      FK  "→ users.user_id"
        timestamp last_seen        "default CURRENT_DATE"
    }

    TICKETS {
        varchar   ticket_id         PK  "NOT NULL"
        varchar   severity
        varchar   status
        varchar   assignment_group
        int4      user_id           FK  "→ users.user_id"
        varchar   device_id         FK  "→ devices.device_id"
        varchar   category
        timestamp created_at
        varchar   subject
        text      description_text
        varchar   ticket_type
        varchar   source_language
    }

    USERS ||--o{ DEVICES : "owns (user_id)"
    USERS ||--o{ TICKETS : "submits (user_id)"
    DEVICES ||--o{ TICKETS : "referenced by (device_id)"
```

---

## DDL for Each Table

### `users`
```sql
-- demo.users definition
CREATE TABLE demo.users (
    user_id int4 GENERATED ALWAYS AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 2147483647 START 1 CACHE 1 NO CYCLE) NOT NULL,
    last_name varchar(100) NULL,
    first_name varchar(100) NULL,
    username varchar(100) NULL,
    department varchar(100) NULL,
    email varchar(200) NULL,
    device_id varchar(20) NULL,
    CONSTRAINT users_device_id_key UNIQUE (device_id),
    CONSTRAINT users_pkey PRIMARY KEY (user_id)
);
```

### `devices`
```sql
-- demo.devices definition
CREATE TABLE demo.devices (
    device_id varchar(20) NOT NULL,
    device_type varchar(100) NULL,
    vpn_client varchar(50) NULL,
    status varchar(50) DEFAULT 'Active'::character varying NULL,
    user_id int4 NULL,
    last_seen timestamp DEFAULT CURRENT_DATE NULL,
    CONSTRAINT devices_pkey PRIMARY KEY (device_id)
);
ALTER TABLE demo.devices ADD CONSTRAINT devices_user_id_fkey FOREIGN KEY (user_id) REFERENCES demo.users(user_id);
```

### `tickets`
```sql
-- demo.tickets definition
CREATE TABLE demo.tickets (
    ticket_id varchar(20) NOT NULL,
    severity varchar(50) NULL,
    status varchar(50) NULL,
    assignment_group varchar(100) NULL,
    user_id int4 NULL,
    device_id varchar(20) NULL,
    category varchar(100) NULL,
    created_at timestamp NULL,
    subject varchar(255) NULL,
    description_text text NULL,
    ticket_type varchar(50) NULL,
    source_language varchar(50) NULL,
    CONSTRAINT tickets_pkey PRIMARY KEY (ticket_id)
);
CREATE INDEX idx_tickets_created_at ON demo.tickets USING btree (created_at);
CREATE INDEX idx_tickets_status ON demo.tickets USING btree (status);
CREATE INDEX idx_tickets_user_id ON demo.tickets USING btree (user_id);
ALTER TABLE demo.tickets ADD CONSTRAINT tickets_device_id_fkey FOREIGN KEY (device_id) REFERENCES demo.devices(device_id);
ALTER TABLE demo.tickets ADD CONSTRAINT tickets_user_id_fkey FOREIGN KEY (user_id) REFERENCES demo.users(user_id);
```

---

## Relationships

| Relationship | Cardinality | Foreign Key | Description |
|---|---|---|---|
| `USERS` → `DEVICES` | One-to-many | `devices.user_id → users.user_id` | A user can own multiple devices. `users.device_id` (UNIQUE) is a denormalized back-reference to the user's primary device for fast lookups. |
| `USERS` → `TICKETS` | One-to-many | `tickets.user_id → users.user_id` | A user can have many support tickets. |
| `DEVICES` → `TICKETS` | One-to-many | `tickets.device_id → devices.device_id` | A ticket can be linked to the specific device involved in the issue. |

## Indexes on `demo.tickets`

| Index | Column | Purpose |
|---|---|---|
| `idx_tickets_user_id` | `user_id` | Fast lookup of all tickets for a given user |
| `idx_tickets_status` | `status` | Filter tickets by status (Open, Resolved, etc.) |
| `idx_tickets_created_at` | `created_at` | Range queries and sorting by creation date |

## Notes

- `users.device_id` carries a `UNIQUE` constraint but **no explicit FK** in the DDL — it is a convenience column. The authoritative ownership direction is `devices.user_id → users.user_id`.
- All three tables live in the `demo` schema.
- `users.user_id` is an `IDENTITY` column (auto-increment); all other PKs are application-assigned `varchar` values.
