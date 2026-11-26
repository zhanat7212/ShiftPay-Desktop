import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

@dataclass
class Shift:
    user_id: int
    shift_date: date
    start: str
    end: str
    break_minutes: int
    pay_type: str
    rate_or_amount: Decimal
    work_minutes: int
    total: Decimal
    paid: str = "no"
    shift_id: str = field(default_factory=lambda: uuid4().hex)


def parse_time(value):
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        raise ValueError("Уақытты СС:ММ пішімінде енгізіңіз. Мысалы, 16:00.")
    return datetime.strptime(value, "%H:%M").time()


def gross_minutes(shift_date, start, end):
    begins = datetime.combine(shift_date, parse_time(start))
    finishes = datetime.combine(shift_date, parse_time(end))
    if finishes == begins:
        raise ValueError("Басталу және аяқталу уақыты бірдей. Аяқталу уақытын қайта енгізіңіз.")
    if finishes < begins:
        finishes += timedelta(days=1)
    return (finishes - begins) // timedelta(minutes=1)


def parse_break(value, duration):
    if not re.fullmatch(r"[0-9]{1,4}", value) or int(value) >= duration:
        raise ValueError(f"Үзіліс 0 мен {duration - 1} минут аралығында болуы керек.")
    return int(value)


def parse_amount(value):
    if not re.fullmatch(r"[0-9]{1,9}(?:[.,][0-9]{1,2})?", value):
        raise ValueError("Теріс емес соманы енгізіңіз. Мысалы, 1100 немесе 1100,50.")
    return Decimal(value.replace(",", "."))


def make_shift(user_id, shift_date, start, end, rest, pay_type, amount):
    minutes = gross_minutes(shift_date, start, end) - rest
    total = Decimal(minutes) * amount / 60 if pay_type == "hourly" else amount
    total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return Shift(user_id, shift_date, start, end, rest, pay_type, amount, minutes, total)


def month_summary(rows):
    paid = sum((Decimal(row["total"]) for row in rows if row["paid"] == "yes"), Decimal(0))
    unpaid = sum((Decimal(row["total"]) for row in rows if row["paid"] != "yes"), Decimal(0))
    minutes = sum(int(row["work_minutes"]) for row in rows)
    return minutes, paid + unpaid, paid, unpaid


def format_duration(minutes):
    hours, remainder = divmod(minutes, 60)
    return f"{hours} сағ {remainder:02d} мин"


def format_money(amount):
    return f"{Decimal(amount):,.2f}".replace(",", " ").replace(".", ",") + " ₸"
