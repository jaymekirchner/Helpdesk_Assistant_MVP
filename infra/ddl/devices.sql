-- demo.devices definition

-- Drop table

-- DROP TABLE demo.devices;

CREATE TABLE demo.devices (
	device_id varchar(20) NOT NULL,
	device_type varchar(100) NULL,
	vpn_client varchar(50) NULL,
	status varchar(50) DEFAULT 'Active'::character varying NULL,
	user_id int4 NULL,
	last_seen timestamp DEFAULT CURRENT_DATE NULL,
	CONSTRAINT devices_pkey PRIMARY KEY (device_id)
);


-- demo.devices foreign keys

ALTER TABLE demo.devices ADD CONSTRAINT devices_user_id_fkey FOREIGN KEY (user_id) REFERENCES demo.users(user_id);