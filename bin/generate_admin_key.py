"""Generate secure admin key for API authentication."""

import secrets

if __name__ == "__main__":
    # Generate 256-bit random key (URL-safe base64)
    key = secrets.token_urlsafe(32)

    print("=" * 60)
    print("Generated Admin Key:")
    print("=" * 60)
    print(key)
    print("=" * 60)
    print()
    print("Set as environment variable:")
    print(f'export TALOS_ADMIN_KEY="{key}"')
    print()
    print("Or add to config/api_auth.yaml:")
    print(f'admin_key: "{key}"')
    print("=" * 60)
