import unittest

import hashlib

from scripts.apply_additive_migration import statements_from_sql, verify_expected_hash


class ApplyAdditiveMigrationTests(unittest.TestCase):
    def test_accepts_create_only(self):
        statements = statements_from_sql(
            "-- comment\nCREATE TABLE IF NOT EXISTS x (id TEXT);\n"
            "CREATE INDEX IF NOT EXISTS ix_x ON x(id);\n"
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_x ON x(id);"
        )
        self.assertEqual(len(statements), 3)

    def test_rejects_mutating_or_destructive_sql(self):
        for sql in (
            "ALTER TABLE x ADD COLUMN y TEXT;",
            "DROP TABLE x;",
            "DELETE FROM x;",
            "INSERT INTO x VALUES (1);",
        ):
            with self.assertRaisesRegex(ValueError, "non-additive"):
                statements_from_sql(sql)

    def test_requires_exact_reviewed_hash(self):
        raw = b"CREATE TABLE IF NOT EXISTS x (id TEXT);"
        expected = hashlib.sha256(raw).hexdigest()
        self.assertEqual(verify_expected_hash(raw, expected), expected)
        with self.assertRaisesRegex(ValueError, "does not match"):
            verify_expected_hash(raw, "0" * 64)

    def test_rejects_malformed_expected_hash(self):
        with self.assertRaisesRegex(ValueError, "64 lowercase"):
            verify_expected_hash(b"x", "ABC")


if __name__ == "__main__":
    unittest.main()
