from __future__ import annotations

import csv
import io
import json
import quopri
import os
import re
from typing import Any

# Column headers we accept, lowercased. Google Contacts exports use
# "Phone 1 - Value" and "Name"; hand-rolled sheets use something simpler.
NAME_HINTS = ("name", "full name", "display name", "contact")
PHONE_HINTS = ("phone", "number", "tel", "mobile", "msisdn")

# Enough digits to identify a subscriber without tripping over country codes
# or a national trunk prefix: +20 10 2116 3069 and 010 2116 3069 are one person.
MATCH_DIGITS = 9


def normalise_number(raw: str) -> str:
    """Strip formatting, collapse an international 00 prefix to +."""
    text = raw.strip()
    plus = text.startswith("+") or text.startswith("00")
    digits = re.sub(r"\D", "", text)
    if text.startswith("00"):
        digits = digits[2:]
    return ("+" + digits) if plus else digits


def match_key(raw: str) -> str:
    """Identity used to decide whether two rows are the same contact."""
    return re.sub(r"\D", "", raw)[-MATCH_DIGITS:]


# Google exports pair every "Phone N - Value" with a "Phone N - Type" whose
# content is "Mobile"/"Home". Both contain "phone", so the type column has to
# lose on purpose or we import the word "Mobile" as a number.
DISQUALIFYING = ("type", "label")


def _pick(headers: list[str], hints: tuple[str, ...]) -> str | None:
    lowered = {h: h.lower().strip() for h in headers}
    candidates = {h: low for h, low in lowered.items()
                  if not any(bad in low for bad in DISQUALIFYING)}
    for h, low in candidates.items():
        if low in hints:
            return h
    # "Phone 1 - Value" should beat a bare "Phone" only by containing a hint;
    # first match in file order is fine once type columns are excluded.
    for h, low in candidates.items():
        if any(hint in low for hint in hints):
            return h
    return None


def _parse_csv(text: str) -> tuple[list[tuple[str, str]], int]:
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    name_col = _pick(headers, NAME_HINTS)
    phone_col = _pick(headers, PHONE_HINTS)
    if name_col is None or phone_col is None:
        raise ValueError(
            f"could not find a name column and a phone column in {headers!r}"
        )
    pairs: list[tuple[str, str]] = []
    skipped = 0
    for row in reader:
        name = (row.get(name_col) or "").strip()
        number = (row.get(phone_col) or "").strip()
        if name and number:
            pairs.append((name, number))
        else:
            skipped += 1
    return pairs, skipped


def _unfold(text: str) -> list[str]:
    """Rejoin folded vCard lines.

    Two different continuation rules are in play. RFC 6350 folding marks a
    continuation with a leading space or tab. Quoted-printable values (vCard
    2.1, which is what Android exports for non-ASCII names) instead end the
    line with a bare "=" and continue in column one.
    """
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if lines and lines[-1].endswith("=") and "QUOTED-PRINTABLE" in lines[-1].upper():
            lines[-1] = lines[-1][:-1] + raw.strip()
        elif raw[:1] in (" ", "\t") and lines:
            lines[-1] += " " + raw.strip()
        else:
            lines.append(raw)
    return lines


def _decode_value(params: str, value: str) -> str:
    """Decode a property value according to its ENCODING/CHARSET params."""
    upper = params.upper()
    if "QUOTED-PRINTABLE" not in upper:
        return value
    charset = "utf-8"
    for part in params.split(";"):
        if part.strip().upper().startswith("CHARSET="):
            charset = part.split("=", 1)[1].strip() or "utf-8"
    try:
        return quopri.decodestring(value.encode("ascii")).decode(charset, "replace")
    except (ValueError, LookupError):
        return value


def _card_name(fn: str, n: str) -> str:
    if fn:
        return fn
    # N is Family;Given;Middle;Prefix;Suffix -- render as "Given Family".
    parts = [p.strip() for p in n.split(";")]
    family = parts[0] if parts else ""
    given = parts[1] if len(parts) > 1 else ""
    return " ".join(p for p in (given, family) if p)


def _parse_vcards(text: str) -> tuple[list[tuple[str, str]], int]:
    pairs: list[tuple[str, str]] = []
    skipped = 0
    fn = n = ""
    tels: list[str] = []
    for line in _unfold(text):
        upper = line.upper()
        if upper.startswith("BEGIN:VCARD"):
            fn = n = ""
            tels = []
        elif upper.startswith("END:VCARD"):
            name = _card_name(fn, n)
            if name and tels:
                pairs.extend((name, t) for t in tels)
            else:
                skipped += 1
        elif ":" in line:
            prop_raw, _, value = line.partition(":")
            prop = prop_raw.split(";", 1)[0].strip().upper()
            params = prop_raw[len(prop_raw.split(";", 1)[0]):]
            value = _decode_value(params, value.strip())
            if prop == "FN":
                fn = value
            elif prop == "N":
                n = value
            elif prop == "TEL" and value:
                tels.append(value)
    if not pairs and not skipped:
        raise ValueError("no usable vCard entries found")
    return pairs, skipped


class ContactStore:
    """A phone book on disk, populated by CSV import.

    Exists because the phone's own address book is unreachable: ColorOS
    refuses Bluetooth PBAP and KDE Connect's contacts plugin returns nothing
    without Android permissions we cannot grant from here.
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._contacts: dict[str, dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, json.JSONDecodeError):
            # A missing or corrupt book must not stop the daemon starting.
            self._contacts = {}
            return
        if isinstance(raw, dict):
            self._contacts = {k: v for k, v in raw.items() if isinstance(v, dict)}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._contacts, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self._path)

    def import_file(self, path: str) -> dict[str, int]:
        """Import contacts from a CSV or vCard file.

        Dispatch is on content, not extension: phones hand out .vcf files
        with arbitrary names and people rename them.
        """
        if not os.path.exists(path):
            raise ValueError(f"file not found: {path}")
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            text = fh.read()
        if "BEGIN:VCARD" in text.upper():
            pairs, skipped = _parse_vcards(text)
        else:
            pairs, skipped = _parse_csv(text)
        return self._merge(pairs, skipped)

    # Kept so existing callers and docs that say "csv" still work.
    import_csv = import_file

    def _merge(self, pairs: list[tuple[str, str]], skipped: int) -> dict[str, int]:
        added = updated = 0
        for name, number in pairs:
            key = match_key(number)
            if not key or not name:
                skipped += 1
                continue
            entry = {"name": name, "number": normalise_number(number)}
            existing = self._contacts.get(key)
            if existing is None:
                self._contacts[key] = entry
                added += 1
            elif existing != entry:
                self._contacts[key] = entry
                updated += 1
        self._save()
        return {"added": added, "updated": updated, "skipped": skipped}

    def all(self) -> list[dict[str, str]]:
        return sorted(self._contacts.values(), key=lambda c: c["name"].casefold())

    def name_for(self, number: str) -> str | None:
        entry = self._contacts.get(match_key(number))
        return entry["name"] if entry else None
