"""Synthetic CRM customer-profile export for volume tests (D13). Invented names only; no real data.

Usage: python tools/generate_synthetic.py --rows 100000 --out synthetic_100k.csv --seed 42
"""
import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

HEADER = ["Loyalty Card", "Prenume", "Nume familie", "Email", "Telefon", "Aplicatie", "Acord GDPR",
          "Newsletter", "Ultima_Interactiune", "Ultima_Achizitie", "Valoare Bon", "Oras"]
FIRST = ["Ana", "Ion", "Maria", "Andrei", "Elena", "Mihai", "Ioana", "Radu", "Ştefan", "Cristina"]
LAST = ["Popescu", "Ionescu", "Țurcanu", "Dumitru", "Stan", "Marin", "Şerban", "Tudor", "Lazăr", "Matei"]
CITIES = ["Bucuresti", "Cluj", "Iasi", "Timisoara", "Brasov", ""]
CONSENT = ["da", "Da", "yes", "nu", "refuz", "1", "0"]
SUBSCRIPTION = ["activ", "Activ", "active", "inactiv", "unsubscribed", "da", "nu"]


def _row(rng: random.Random, card: str, today: date) -> list[str]:
    first, last = rng.choice(FIRST), rng.choice(LAST)
    email = f"{first.lower()}.{last.lower()}{rng.randint(1, 999)}@example.com"
    phone = "07" + "".join(str(rng.randint(0, 9)) for _ in range(8))
    seen = today - timedelta(days=rng.randint(0, 730))
    bought = seen - timedelta(days=rng.randint(0, 60))
    amount = f"{rng.randint(5, 900)}.{rng.randint(0, 99):02d}"
    row = [card, first, last, email, phone, rng.choice(["da", "nu", "yes", "no"]), rng.choice(CONSENT),
           rng.choice(SUBSCRIPTION), seen.strftime(rng.choice(["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"])),
           bought.isoformat(), amount, rng.choice(CITIES)]
    roll = rng.random()
    if roll < 0.003:
        row[0] = rng.choice(["", "1234 5678", "1.23457E+15"])          # rejected
    elif roll < 0.008:
        row[3] = email.replace("@", "@@")                                # EMAIL_INVALID
    elif roll < 0.018:
        row[4] = phone[1:]                                               # PHONE_LEADING_ZERO
    elif roll < 0.028:
        row[6] = rng.choice(["", "poate"])                               # CONSENT_UNKNOWN
    elif roll < 0.030:
        row[3], row[4], row[5] = "", "", "nu"                            # NO_CONTACT_CHANNEL
    elif roll < 0.032:
        row[10] = rng.choice(["-5", "0", "12 lei"])                      # PURCHASE_AMOUNT_INVALID
    return row


def generate(rows: int, out: Path, seed: int = 42, today: date = date(2026, 11, 1)) -> None:
    rng = random.Random(seed)
    cards: list[str] = []
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(HEADER)
        for _ in range(rows):
            if cards and rng.random() < 0.006:
                card = rng.choice(cards)                                 # duplicate of an earlier card
            else:
                card = f"{rng.randint(10**15, 10**16 - 1)}"
                cards.append(card)
            writer.writerow(_row(rng, card, today))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    generate(args.rows, args.out, args.seed)


if __name__ == "__main__":
    main()
