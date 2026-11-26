import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
PORT = "55437"
LOGIN_PATTERN = re.compile(r"[a-z0-9_.-]{3,32}")
PASSWORD_SALT = bytes(16)


class DatabaseError(Exception):
    pass


def derive_key(password, salt):
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**17, r=8, p=1,
        maxmem=256 * 1024 * 1024, dklen=32,
    )


def password_hash(password):
    salt = secrets.token_bytes(16)
    return f"scrypt-v1${salt.hex()}${derive_key(password, salt).hex()}"


def matches_password(password, stored):
    if not stored:
        derive_key(password, PASSWORD_SALT)
        return False
    version, salt, expected = stored.split("$")
    if version != "scrypt-v1":
        return False
    return hmac.compare_digest(derive_key(password, bytes.fromhex(salt)), bytes.fromhex(expected))


def postgres_binary(name):
    custom = os.environ.get("SHIFTPAY_PG_BIN")
    if custom:
        path = Path(custom) / name
        if path.is_file():
            return str(path)
    installed = shutil.which(name)
    if installed:
        return installed
    for prefix in ("/opt/homebrew", "/usr/local"):
        path = Path(prefix) / "opt" / "postgresql@17" / "bin" / name
        if path.is_file():
            return str(path)
    raise DatabaseError("PostgreSQL 17 табылмады. README.md файлындағы орнату қадамын қараңыз.")


def run_postgres(args, *, script=None, timeout=25, check=True, connection_url=None):
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    env.update(PGCONNECT_TIMEOUT="3", PGCLIENTENCODING="UTF8")
    if connection_url:
        env["PGDATABASE"] = connection_url
    try:
        result = subprocess.run(
            args, input=script, capture_output=True, encoding="utf-8",
            errors="replace", env=env, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DatabaseError(f"PostgreSQL іске қосылған жоқ. {error}") from error
    if check and result.returncode:
        raise DatabaseError(result.stderr.strip() or result.stdout.strip() or "PostgreSQL қатесі.")
    return result


def local_cluster():
    identity = hashlib.sha256(os.fsencode(ROOT)).hexdigest()[:14]
    socket = Path("/tmp") / f"shiftpay-{os.getuid()}-{identity}"
    socket.mkdir(mode=0o700, exist_ok=True)
    if socket.is_symlink() or socket.stat().st_uid != os.getuid() or socket.stat().st_mode & 0o077:
        raise DatabaseError("PostgreSQL сокет бумасының рұқсаттарын тексеріңіз.")
    state = ROOT / ".local"
    state.mkdir(mode=0o700, exist_ok=True)
    return socket, state


def start_local_postgres():
    socket, state = local_cluster()
    data = state / "postgres"
    control = postgres_binary("pg_ctl")
    # An OS lock prevents simultaneous VS Code runs from initializing the same cluster.
    with (state / "startup.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (data / "PG_VERSION").is_file():
            # Build the cluster in a sibling directory so interrupted setup can be retried.
            with tempfile.TemporaryDirectory(dir=state, prefix="init-") as temp:
                staging = Path(temp) / "postgres"
                run_postgres([
                    postgres_binary("initdb"), "-D", str(staging), "--no-locale",
                    "--encoding=UTF8", "--auth-local=peer", "--auth-host=scram-sha-256",
                ], timeout=90)
                staging.rename(data)
        status = run_postgres([control, "-D", str(data), "status"], check=False)
        if status.returncode:
            options = shlex.join(["-c", "listen_addresses=", "-k", str(socket), "-p", PORT])
            try:
                run_postgres([
                    control, "-D", str(data), "-l", str(state / "postgres.log"),
                    "-o", options, "-w", "-t", "15", "start",
                ])
            except DatabaseError as error:
                raise DatabaseError(f"{error}\nЛог: {state / 'postgres.log'}") from error
    return ["-h", str(socket), "-p", PORT, "-d", "postgres"]


class Database:
    def __init__(self):
        binary = postgres_binary("psql")
        self.connection_url = os.environ.get("SHIFTPAY_DATABASE_URL")
        connection = [] if self.connection_url else start_local_postgres()
        self.command = [binary, "-X", "-qAt", "--no-password", "-v", "ON_ERROR_STOP=1", *connection]
        self.query((ROOT / "schema.sql").read_text(encoding="utf-8"))

    def query(self, sql, *parameters):
        # Send values as hex through stdin. psql quotes them as SQL literals before decoding.
        variables = "".join(
            f"\\set p{index} '{str(value).encode('utf-8').hex()}'\n"
            for index, value in enumerate(parameters, start=1)
        )
        result = run_postgres(
            self.command, script=variables + sql + "\n", connection_url=self.connection_url,
        )
        return [json.loads(line) for line in result.stdout.splitlines() if line]

    def register(self, login, password):
        rows = self.query("""
            INSERT INTO shiftpay.users (login, password_hash)
            VALUES (convert_from(decode(:'p1','hex'),'UTF8'), convert_from(decode(:'p2','hex'),'UTF8'))
            ON CONFLICT (login) DO NOTHING
            RETURNING id;
        """, login, password_hash(password))
        return bool(rows)

    def authenticate(self, login, password):
        rows = self.query("""
            SELECT json_build_object('id', id, 'hash', password_hash)
            FROM shiftpay.users WHERE login = convert_from(decode(:'p1','hex'),'UTF8');
        """, login)
        account = rows[0] if rows else None
        if matches_password(password, account["hash"] if account else None):
            return account["id"]
        return False

    def save_shift(self, shift):
        self.query("""
            INSERT INTO shiftpay.shifts
                (shift_id, user_id, shift_date, start_time, end_time, break_minutes,
                 pay_type, rate_or_amount, work_minutes, total)
            SELECT p[1]::uuid, p[2]::bigint, p[3]::date, p[4]::time, p[5]::time,
                   p[6]::integer, p[7], p[8]::numeric, p[9]::integer, p[10]::numeric
            FROM (SELECT ARRAY(
                SELECT json_array_elements_text(convert_from(decode(:'p1','hex'),'UTF8')::json)
            ) AS p) values_for_shift
            ON CONFLICT (shift_id) DO NOTHING;
        """, json.dumps([
            shift.shift_id, shift.user_id, shift.shift_date.isoformat(), shift.start, shift.end,
            shift.break_minutes, shift.pay_type, str(shift.rate_or_amount), shift.work_minutes,
            str(shift.total),
        ]))
        return True

    def shifts_for_month(self, user_id, month):
        return self.query("""
            SELECT json_build_object(
                'shift_id', shift_id, 'shift_date', to_char(shift_date, 'DD.MM.YYYY'),
                'start', to_char(start_time, 'HH24:MI'), 'end', to_char(end_time, 'HH24:MI'),
                'total', total::text, 'work_minutes', work_minutes,
                'paid', CASE WHEN paid THEN 'yes' ELSE 'no' END
            )
            FROM shiftpay.shifts
            WHERE user_id = convert_from(decode(:'p1','hex'),'UTF8')::bigint
              AND shift_date >= convert_from(decode(:'p2','hex'),'UTF8')::date
              AND shift_date < convert_from(decode(:'p2','hex'),'UTF8')::date + interval '1 month'
            ORDER BY shift_date DESC, start_time DESC, shift_id;
        """, user_id, month)

    def mark_paid(self, user_id, shift_id, paid):
        self.query("""
            UPDATE shiftpay.shifts SET paid = convert_from(decode(:'p3','hex'),'UTF8')::boolean
            WHERE user_id = convert_from(decode(:'p1','hex'),'UTF8')::bigint
              AND shift_id = convert_from(decode(:'p2','hex'),'UTF8')::uuid;
        """, user_id, shift_id, str(paid).lower())


if __name__ == "__main__":
    _, state = local_cluster()
    run_postgres([postgres_binary("pg_ctl"), "-D", str(state / "postgres"), "-w", "stop"])
