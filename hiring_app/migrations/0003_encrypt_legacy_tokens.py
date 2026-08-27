"""
Encrypt any GoogleOAuthToken.token_json rows written before EncryptedTextField
existed (migration 0002 only changes the Python-level field class — it does
not touch existing bytes in the column, which are still plaintext JSON).

Uses raw SQL rather than the ORM: reading through the model now calls
EncryptedTextField.from_db_value, which tries to Fernet-decrypt every value it
sees and raises on anything that isn't already ciphertext — including the
exact plaintext rows this migration exists to fix.

Idempotent: a value that already decrypts cleanly is left alone, so re-running
this (or running it against a fresh, empty production DB) is a no-op.
"""
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import migrations


def _fernet():
    return Fernet(settings.FIELD_ENCRYPTION_KEY)


def encrypt_legacy_tokens(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT id, token_json FROM hiring_app_googleoauthtoken")
        rows = cursor.fetchall()

        f = _fernet()
        for row_id, raw_value in rows:
            if not raw_value:
                continue
            try:
                f.decrypt(raw_value.encode('ascii'))
                continue  # already ciphertext — nothing to do
            except (InvalidToken, ValueError, UnicodeEncodeError):
                pass  # plaintext (or garbage) — encrypt it below

            encrypted = f.encrypt(raw_value.encode('utf-8')).decode('ascii')
            cursor.execute(
                "UPDATE hiring_app_googleoauthtoken SET token_json = %s WHERE id = %s",
                [encrypted, row_id],
            )


def decrypt_back_to_plaintext(apps, schema_editor):
    """Reverse: only meaningful if you also revert model 0002 by hand."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT id, token_json FROM hiring_app_googleoauthtoken")
        rows = cursor.fetchall()

        f = _fernet()
        for row_id, raw_value in rows:
            if not raw_value:
                continue
            try:
                plain = f.decrypt(raw_value.encode('ascii')).decode('utf-8')
            except (InvalidToken, ValueError, UnicodeEncodeError):
                continue  # already plaintext
            cursor.execute(
                "UPDATE hiring_app_googleoauthtoken SET token_json = %s WHERE id = %s",
                [plain, row_id],
            )


class Migration(migrations.Migration):

    dependencies = [
        ('hiring_app', '0002_campaign_candidate'),
    ]

    operations = [
        migrations.RunPython(encrypt_legacy_tokens, decrypt_back_to_plaintext),
    ]
