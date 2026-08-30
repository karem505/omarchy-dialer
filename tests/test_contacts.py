from __future__ import annotations

import json

import pytest

from dialerd.contacts import ContactStore, normalise_number


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_normalise_strips_formatting():
    assert normalise_number("+20 100 000 0001") == "+201000000001"
    assert normalise_number("(010) 0000-0001") == "01000000001"


def test_normalise_keeps_leading_plus_only():
    assert normalise_number("00201000000001") == "+201000000001"


def test_match_key_ignores_country_and_trunk_prefix():
    # +201000000001 and 01000000001 are the same Egyptian mobile.
    from dialerd.contacts import match_key
    assert match_key("+201000000001") == match_key("01000000001")


def test_import_simple_csv(tmp_path):
    path = write(tmp_path, "c.csv", "name,phone\nAhmed,+201000000001\nMona,01000000008\n")
    store = ContactStore(str(tmp_path / "db.json"))
    result = store.import_csv(path)
    assert result == {"added": 2, "updated": 0, "skipped": 0}
    assert {c["name"] for c in store.all()} == {"Ahmed", "Mona"}


def test_import_google_contacts_export(tmp_path):
    path = write(tmp_path, "g.csv",
        "Name,Given Name,Family Name,Phone 1 - Type,Phone 1 - Value\n"
        "Ahmed Hassan,Ahmed,Hassan,Mobile,+201000000001\n")
    store = ContactStore(str(tmp_path / "db.json"))
    assert store.import_csv(path) == {"added": 1, "updated": 0, "skipped": 0}
    assert store.all()[0]["name"] == "Ahmed Hassan"


def test_reimport_updates_name_instead_of_duplicating(tmp_path):
    db = str(tmp_path / "db.json")
    a = write(tmp_path, "a.csv", "name,phone\nAhmed,+201000000001\n")
    b = write(tmp_path, "b.csv", "name,phone\nAhmed Hassan,+201000000001\n")
    store = ContactStore(db)
    store.import_csv(a)
    assert store.import_csv(b) == {"added": 0, "updated": 1, "skipped": 0}
    assert len(store.all()) == 1
    assert store.all()[0]["name"] == "Ahmed Hassan"


def test_reimport_identical_row_is_not_counted_as_update(tmp_path):
    db = str(tmp_path / "db.json")
    a = write(tmp_path, "a.csv", "name,phone\nAhmed,+201000000001\n")
    store = ContactStore(db)
    store.import_csv(a)
    assert store.import_csv(a) == {"added": 0, "updated": 0, "skipped": 0}


def test_rows_without_a_number_are_skipped(tmp_path):
    path = write(tmp_path, "c.csv", "name,phone\nNoNumber,\nAhmed,+20102\n")
    store = ContactStore(str(tmp_path / "db.json"))
    assert store.import_csv(path) == {"added": 1, "updated": 0, "skipped": 1}


def test_import_is_persisted_across_instances(tmp_path):
    db = str(tmp_path / "db.json")
    path = write(tmp_path, "c.csv", "name,phone\nAhmed,+201000000001\n")
    ContactStore(db).import_csv(path)
    assert ContactStore(db).all()[0]["name"] == "Ahmed"


def test_missing_file_raises_clear_error(tmp_path):
    store = ContactStore(str(tmp_path / "db.json"))
    with pytest.raises(ValueError, match="not found"):
        store.import_csv(str(tmp_path / "nope.csv"))


def test_csv_without_recognisable_columns_raises(tmp_path):
    path = write(tmp_path, "bad.csv", "colour,shape\nred,circle\n")
    store = ContactStore(str(tmp_path / "db.json"))
    with pytest.raises(ValueError, match="column"):
        store.import_csv(path)


def test_corrupt_db_does_not_crash_startup(tmp_path):
    db = tmp_path / "db.json"
    db.write_text("{{{not json", encoding="utf-8")
    assert ContactStore(str(db)).all() == []


def test_lookup_by_number_returns_name(tmp_path):
    db = str(tmp_path / "db.json")
    path = write(tmp_path, "c.csv", "name,phone\nAhmed,+201000000001\n")
    store = ContactStore(db)
    store.import_csv(path)
    assert store.name_for("01000000001") == "Ahmed"
    assert store.name_for("+999999") is None


def test_all_is_sorted_by_name(tmp_path):
    path = write(tmp_path, "c.csv", "name,phone\nZaid,+2011\nAhmed,+2012\n")
    store = ContactStore(str(tmp_path / "db.json"))
    store.import_csv(path)
    assert [c["name"] for c in store.all()] == ["Ahmed", "Zaid"]


VCARD = """BEGIN:VCARD
VERSION:3.0
FN:Ahmed Hassan
N:Hassan;Ahmed;;;
TEL;TYPE=CELL:+201000000001
END:VCARD
BEGIN:VCARD
VERSION:3.0
FN:Mona Farid
TEL;TYPE=HOME:01000000008
END:VCARD
"""


def test_import_vcf(tmp_path):
    path = write(tmp_path, "c.vcf", VCARD)
    store = ContactStore(str(tmp_path / "db.json"))
    assert store.import_file(path) == {"added": 2, "updated": 0, "skipped": 0}
    assert {c["name"] for c in store.all()} == {"Ahmed Hassan", "Mona Farid"}


def test_vcf_falls_back_to_structured_name_without_fn(tmp_path):
    path = write(tmp_path, "c.vcf",
        "BEGIN:VCARD\nN:Hassan;Ahmed;;;\nTEL:+201000000001\nEND:VCARD\n")
    store = ContactStore(str(tmp_path / "db.json"))
    store.import_file(path)
    assert store.all()[0]["name"] == "Ahmed Hassan"


def test_vcf_card_with_multiple_numbers_yields_one_entry_each(tmp_path):
    path = write(tmp_path, "c.vcf",
        "BEGIN:VCARD\nFN:Ahmed\nTEL;TYPE=CELL:+201000000001\n"
        "TEL;TYPE=WORK:+201000000006\nEND:VCARD\n")
    store = ContactStore(str(tmp_path / "db.json"))
    assert store.import_file(path)["added"] == 2
    assert all(c["name"] == "Ahmed" for c in store.all())


def test_vcf_unfolds_continuation_lines(tmp_path):
    # RFC 6350 folds long lines; a leading space continues the previous one.
    path = write(tmp_path, "c.vcf",
        "BEGIN:VCARD\nFN:Ahmed Very Long\n  Name Here\nTEL:+201000000001\nEND:VCARD\n")
    store = ContactStore(str(tmp_path / "db.json"))
    store.import_file(path)
    assert store.all()[0]["name"] == "Ahmed Very Long Name Here"


def test_vcf_card_without_tel_is_skipped(tmp_path):
    path = write(tmp_path, "c.vcf", "BEGIN:VCARD\nFN:NoPhone\nEND:VCARD\n")
    store = ContactStore(str(tmp_path / "db.json"))
    assert store.import_file(path) == {"added": 0, "updated": 0, "skipped": 1}


def test_vcf_reimport_updates_rather_than_duplicates(tmp_path):
    db = str(tmp_path / "db.json")
    a = write(tmp_path, "a.vcf", "BEGIN:VCARD\nFN:Ahmed\nTEL:+201000000001\nEND:VCARD\n")
    b = write(tmp_path, "b.vcf", "BEGIN:VCARD\nFN:Ahmed Hassan\nTEL:+201000000001\nEND:VCARD\n")
    store = ContactStore(db)
    store.import_file(a)
    assert store.import_file(b) == {"added": 0, "updated": 1, "skipped": 0}
    assert len(store.all()) == 1


def test_csv_and_vcf_share_one_book(tmp_path):
    db = str(tmp_path / "db.json")
    csv_path = write(tmp_path, "c.csv", "name,phone\nMona,01000000008\n")
    vcf_path = write(tmp_path, "c.vcf", "BEGIN:VCARD\nFN:Ahmed\nTEL:+201000000001\nEND:VCARD\n")
    store = ContactStore(db)
    store.import_file(csv_path)
    store.import_file(vcf_path)
    assert len(store.all()) == 2


def test_import_file_dispatches_on_content_not_just_extension(tmp_path):
    # A vCard saved with the wrong extension should still import.
    path = write(tmp_path, "mislabelled.csv",
                 "BEGIN:VCARD\nFN:Ahmed\nTEL:+201000000001\nEND:VCARD\n")
    store = ContactStore(str(tmp_path / "db.json"))
    assert store.import_file(path)["added"] == 1


def test_unsupported_format_raises(tmp_path):
    path = write(tmp_path, "x.txt", "just some prose with no structure\n")
    store = ContactStore(str(tmp_path / "db.json"))
    with pytest.raises(ValueError):
        store.import_file(path)


# --- Arabic / non-ASCII ---------------------------------------------------

def test_vcf_plain_utf8_arabic(tmp_path):
    path = write(tmp_path, "ar.vcf",
        "BEGIN:VCARD\nFN:محمد صلاح\nTEL:+201000000003\nEND:VCARD\n")
    store = ContactStore(str(tmp_path / "db.json"))
    store.import_file(path)
    assert store.all()[0]["name"] == "محمد صلاح"


def test_vcf_quoted_printable_arabic(tmp_path):
    # vCard 2.1 from Android encodes non-ASCII names like this.
    path = write(tmp_path, "qp.vcf",
        "BEGIN:VCARD\nVERSION:2.1\n"
        "FN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:=D8=A3=D8=AD=D9=85=D8=AF\n"
        "TEL;CELL:+201000000001\nEND:VCARD\n")
    store = ContactStore(str(tmp_path / "db.json"))
    store.import_file(path)
    assert store.all()[0]["name"] == "أحمد"  # أحمد


def test_quoted_printable_soft_line_break(tmp_path):
    # A trailing '=' continues the value on the next line, with no leading space.
    path = write(tmp_path, "qp2.vcf",
        "BEGIN:VCARD\nVERSION:2.1\n"
        "FN;ENCODING=QUOTED-PRINTABLE;CHARSET=UTF-8:=D8=A3=D8=AD=\n"
        "=D9=85=D8=AF\n"
        "TEL:+201000000001\nEND:VCARD\n")
    store = ContactStore(str(tmp_path / "db.json"))
    store.import_file(path)
    assert store.all()[0]["name"] == "أحمد"


def test_csv_with_arabic_names(tmp_path):
    path = write(tmp_path, "ar.csv",
        "name,phone\nمنى فريد,01000000008\n")
    store = ContactStore(str(tmp_path / "db.json"))
    store.import_file(path)
    assert store.all()[0]["name"] == "منى فريد"


def test_arabic_names_survive_a_save_load_round_trip(tmp_path):
    db = str(tmp_path / "db.json")
    path = write(tmp_path, "ar.csv", "name,phone\nأحمد,+201000000001\n")
    ContactStore(db).import_file(path)
    assert ContactStore(db).all()[0]["name"] == "أحمد"


def test_arabic_name_lookup_for_incoming_call(tmp_path):
    db = str(tmp_path / "db.json")
    path = write(tmp_path, "ar.csv", "name,phone\nأحمد,+201000000001\n")
    store = ContactStore(db)
    store.import_file(path)
    assert store.name_for("01000000001") == "أحمد"
