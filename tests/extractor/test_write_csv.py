"""
Tests for Component._write_csv() — real file I/O with pytest's tmp_path.
"""

import csv

from extractor_component import Component


def read_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


class TestWriteMode:
    def test_creates_file_with_correct_content(self, tmp_path):
        path = tmp_path / "out.csv"
        Component._write_csv(path, [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}])

        rows = read_csv(path)
        assert rows == [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]

    def test_header_written_first(self, tmp_path):
        path = tmp_path / "out.csv"
        Component._write_csv(path, [{"id": 1, "name": "A", "email": "a@x.com"}])

        assert path.read_text().splitlines()[0] == "id,name,email"

    def test_empty_records_does_not_create_file(self, tmp_path):
        path = tmp_path / "out.csv"
        Component._write_csv(path, [])

        assert not path.exists()

    def test_all_field_keys_unioned_across_records(self, tmp_path):
        path = tmp_path / "out.csv"
        Component._write_csv(
            path,
            [
                {"id": 1, "name": "A"},
                {"id": 2, "name": "B", "email": "b@x.com"},
                {"id": 3, "name": "C", "phone": "+1"},
            ],
        )

        rows = read_csv(path)
        assert rows[0]["email"] == ""
        assert rows[0]["phone"] == ""
        assert rows[1]["email"] == "b@x.com"
        assert rows[1]["phone"] == ""
        assert rows[2]["phone"] == "+1"

    def test_none_values_written_as_empty_string(self, tmp_path):
        path = tmp_path / "out.csv"
        Component._write_csv(path, [{"id": 1, "email": None}, {"id": 2, "name": None}])

        rows = read_csv(path)
        assert rows[0]["email"] == ""
        assert rows[1]["name"] == ""


class TestAppendMode:
    def test_appends_records_without_duplicate_header(self, tmp_path):
        path = tmp_path / "out.csv"
        Component._write_csv(path, [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}])
        Component._write_csv(path, [{"id": 3, "name": "C"}, {"id": 4, "name": "D"}], mode="a")

        rows = read_csv(path)
        assert len(rows) == 4
        assert rows[2]["id"] == "3"
        assert rows[3]["id"] == "4"

    def test_same_fields_preserved_correctly(self, tmp_path):
        path = tmp_path / "out.csv"
        Component._write_csv(path, [{"id": 1, "name": "A", "email": "a@x.com"}])
        Component._write_csv(path, [{"id": 2, "name": "B", "email": "b@x.com"}], mode="a")

        rows = read_csv(path)
        assert rows[0]["email"] == "a@x.com"
        assert rows[1]["email"] == "b@x.com"
