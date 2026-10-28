import os
import unittest
import base64
import json
from app.config.settings import settings
from app.services.google_auth_service import google_auth_service, GMAIL_SCOPES
from app.services.email_service import encrypt_password, decrypt_password
from app.database.models import EmailQueue

class TestGoogleAuth(unittest.TestCase):
    def test_authorization_url_generation(self) -> None:
        """Test Google OAuth authorization URL contains necessary OAuth parameters and scopes."""
        user_id = 987654
        auth_url = google_auth_service.get_authorization_url(user_id)
        
        self.assertIn("https://accounts.google.com/o/oauth2/v2/auth", auth_url)
        self.assertIn("response_type=code", auth_url)
        self.assertIn("access_type=offline", auth_url)
        self.assertIn("prompt=consent", auth_url)
        
        # Verify Gmail send scope
        self.assertIn("gmail.send", auth_url)

    def test_state_encode_and_decode(self) -> None:
        """Test encoding user_id in state and decoding it back."""
        user_id = 123456
        auth_url = google_auth_service.get_authorization_url(user_id)
        
        # Extract state parameter from url
        import urllib.parse
        parsed = urllib.parse.urlparse(auth_url)
        params = urllib.parse.parse_qs(parsed.query)
        state = params["state"][0]
        
        decoded_user_id = google_auth_service.decode_state(state)
        self.assertEqual(decoded_user_id, user_id)

    def test_token_encryption_and_decryption(self) -> None:
        """Test symmetric encryption and decryption of OAuth tokens."""
        original_token = "ya29.a0ARrdaM_mock_google_oauth_token_12345"
        encrypted = encrypt_password(original_token)
        self.assertNotEqual(original_token, encrypted)
        
        decrypted = decrypt_password(encrypted)
        self.assertEqual(original_token, decrypted)

    def test_redirect_uri_fallback(self) -> None:
        """Test redirect URI defaults to WEB_BASE_URL callback."""
        uri = google_auth_service.get_redirect_uri()
        self.assertTrue(uri.endswith("/api/auth/google/callback"))

if __name__ == "__main__":
    unittest.main()
