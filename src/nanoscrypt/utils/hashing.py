import hashlib


def calculate_sha256(content: str) -> str:
    """Computes the hex digest of the SHA-256 hash of a string."""
    sha = hashlib.sha256()
    sha.update(content.encode("utf-8"))
    return sha.hexdigest()
