from __future__ import annotations

import unittest
from datetime import datetime

import pandas as pd

from market_staging_content import (
    STAGING_COLUMNS,
    StagingContentDigester,
    StagingContentError,
    digest_rows,
)
from scripts.stage_market_features_to_turso import clean, encode_staging_arg
from turso_read_pipeline import TursoReadPipeline, _encode_arg


def row(ticker="AAA", session="2026-08-27"):
    values = []
    text = {"ticker": ticker, "sector": "Tech", "ras_signal": "HOLD", "analyst_consensus": None, "sector_regime": "BULL", "market_fear_level": "CALM"}
    for name in STAGING_COLUMNS:
        if name == "date":
            values.append(session)
        elif name in text:
            values.append(text[name])
        else:
            values.append(1.0)
    return tuple(values)


class StagingContentTests(unittest.TestCase):
    def test_staging_float_uses_lossless_decimal_text_transport(self):
        value = float.fromhex("0x1.f7bcbfbb9d498p+0")
        encoded = encode_staging_arg(value)
        self.assertEqual(encoded, {"type": "text", "value": "1.9677238305132843"})
        self.assertEqual(float(encoded["value"]).hex(), value.hex())

    def test_prewrite_timestamp_and_persisted_date_string_match(self):
        before = list(row())
        before[1] = datetime(2026, 8, 27)
        self.assertEqual(digest_rows([tuple(before)]), digest_rows([row()]))

    def test_integer_and_real_have_same_persisted_numeric_identity(self):
        a = list(row())
        b = list(row())
        a[8] = 1000
        b[8] = 1000.0
        self.assertEqual(digest_rows([tuple(a)]), digest_rows([tuple(b)]))

    def test_order_and_duplicates_fail_closed(self):
        digester = StagingContentDigester()
        with self.assertRaisesRegex(StagingContentError, "strictly ordered"):
            digester.update([row("BBB"), row("AAA")])
        with self.assertRaisesRegex(StagingContentError, "strictly ordered"):
            digest_rows([row(), row()])

    def test_tamper_changes_digest(self):
        original = row()
        changed = list(original)
        changed[7] = 1.01
        self.assertNotEqual(digest_rows([original]), digest_rows([tuple(changed)]))

    def test_bool_nan_bad_date_and_bad_ticker_reject(self):
        cases = []
        value = list(row()); value[3] = True; cases.append(value)
        value = list(row()); value[3] = float("nan"); cases.append(value)
        value = list(row()); value[1] = "27-08-2026"; cases.append(value)
        value = list(row()); value[0] = "aaa"; cases.append(value)
        value = list(row()); value[0] = None; cases.append(value)
        value = list(row()); value[1] = None; cases.append(value)
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(StagingContentError):
                    digest_rows([tuple(value)])

    def test_all_columns_writer_encode_libsql_decode_roundtrip(self):
        original = list(row(ticker="AAA", session="2026-08-27"))
        original[2] = "Téch/半導体"
        original[3] = -0.0
        original[4] = 7
        original[5] = None
        original[1] = pd.Timestamp(2026, 8, 27, 23, 59)
        encoded = [_encode_arg(clean(value)) for value in original]

        # Simulate libSQL REAL affinity and its exact pipeline response envelope.
        persisted = []
        for value in encoded:
            if value["type"] == "null":
                persisted.append({"type": "null"})
            elif value["type"] in {"integer", "float"}:
                number = float(value["value"])
                persisted.append({"type": "float", "value": 0.0 if number == 0.0 else number})
            else:
                persisted.append(value)

        class Response:
            status_code = 200
            def json(self):
                return {"results": [{"type": "ok", "response": {"result": {
                    "cols": [{"name": name} for name in STAGING_COLUMNS],
                    "rows": [persisted],
                }}}]}

        class Session:
            def post(self, *args, **kwargs):
                return Response()

        readback = TursoReadPipeline(
            "https://example.invalid/v2/pipeline", "token", session=Session()
        ).execute("SELECT " + ",".join(STAGING_COLUMNS), []).rows[0]
        self.assertEqual(digest_rows([tuple(clean(v) for v in original)]), digest_rows([readback]))


if __name__ == "__main__":
    unittest.main()
