CREATE SCHEMA IF NOT EXISTS shiftpay;

CREATE TABLE IF NOT EXISTS shiftpay.users (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    login varchar(32) NOT NULL UNIQUE CHECK (login ~ '^[a-z0-9_.-]{3,32}$'),
    password_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS shiftpay.shifts (
    shift_id uuid PRIMARY KEY,
    user_id bigint NOT NULL REFERENCES shiftpay.users(id),
    shift_date date NOT NULL,
    start_time time NOT NULL,
    end_time time NOT NULL,
    break_minutes integer NOT NULL CHECK (break_minutes BETWEEN 0 AND 1438),
    pay_type text NOT NULL CHECK (pay_type IN ('hourly', 'fixed')),
    rate_or_amount numeric(11, 2) NOT NULL CHECK (rate_or_amount >= 0),
    work_minutes integer NOT NULL CHECK (work_minutes BETWEEN 1 AND 1439),
    total numeric(13, 2) NOT NULL CHECK (total >= 0),
    paid boolean NOT NULL DEFAULT false,
    CHECK (start_time <> end_time)
);
CREATE INDEX IF NOT EXISTS shifts_user_date ON shiftpay.shifts (user_id, shift_date DESC);
