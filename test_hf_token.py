#!/usr/bin/env python3
"""Test script to verify HuggingFace token is set correctly."""

import os
import sys

def test_hf_token():
    """Check if HF_TOKEN is set and valid."""
    print("Checking HuggingFace token configuration...\n")

    # Check environment variable
    token = os.environ.get('HF_TOKEN')

    if token:
        print(f"✓ HF_TOKEN is set")
        print(f"  Token preview: {token[:10]}...{token[-5:] if len(token) > 15 else ''}")
    else:
        print("✗ HF_TOKEN is not set in environment")
        print("\nChecking huggingface-cli login status...")

        try:
            from huggingface_hub import HfFolder
            stored_token = HfFolder.get_token()
            if stored_token:
                print(f"✓ Token found via huggingface-cli login")
                print(f"  Token preview: {stored_token[:10]}...{stored_token[-5:]}")
            else:
                print("✗ No token found via huggingface-cli either")
                print("\n❌ Please set up your HuggingFace token using one of these methods:")
                print("   1. huggingface-cli login")
                print("   2. export HF_TOKEN='your_token'")
                return False
        except ImportError:
            print("✗ huggingface_hub not installed")
            print("\nInstall it with: pip install huggingface_hub")
            return False

    # Test downloading a model (this will use the token)
    print("\nTesting model download (this should not show warnings)...")
    try:
        from sentence_transformers import SentenceTransformer
        import warnings

        # Capture warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')

            # Check for HF_TOKEN warnings
            hf_warnings = [warning for warning in w if 'HF_TOKEN' in str(warning.message)]

            if hf_warnings:
                print("✗ Still seeing HF_TOKEN warnings:")
                for warning in hf_warnings:
                    print(f"  {warning.message}")
                return False
            else:
                print("✓ Model loaded successfully without HF_TOKEN warnings!")
                return True

    except Exception as e:
        print(f"✗ Error loading model: {e}")
        return False

if __name__ == "__main__":
    success = test_hf_token()
    sys.exit(0 if success else 1)
