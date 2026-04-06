-- demo.tickets definition

-- Drop table

-- DROP TABLE demo.tickets;

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


-- demo.tickets foreign keys

ALTER TABLE demo.tickets ADD CONSTRAINT tickets_device_id_fkey FOREIGN KEY (device_id) REFERENCES demo.devices(device_id);
ALTER TABLE demo.tickets ADD CONSTRAINT tickets_user_id_fkey FOREIGN KEY (user_id) REFERENCES demo.users(user_id);