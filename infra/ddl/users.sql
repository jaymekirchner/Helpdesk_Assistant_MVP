-- demo.users definition

-- Drop table

-- DROP TABLE demo.users;

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