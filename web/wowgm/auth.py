import hashlib
import hmac
import re
import secrets

N = int("894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7", 16)

def username(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]{1,16}", value):
        raise ValueError("账号须为 1–16 位字母、数字或下划线")
    return value.upper()

def password(value: str) -> str:
    if not re.fullmatch(r"[!-~]{6,16}", value):
        raise ValueError("密码须为 6–16 位 ASCII 字符，不含空格")
    return value.upper()

def verifier(user: str, secret: str, salt: bytes) -> str:
    # Existing game accounts may have passwords shorter than the web's new-password policy.
    if not re.fullmatch(r"[!-~]{1,16}", secret):
        raise ValueError("Invalid game password")
    identity = hashlib.sha1((username(user) + ":" + secret.upper()).encode("ascii")).digest()
    x = int.from_bytes(hashlib.sha1(salt + identity).digest(), "little")
    return format(pow(7, x, N), "X")

def credentials(user: str, secret: str, salt: bytes | None = None) -> tuple[str, str]:
    password(secret)
    if salt is None:
        raw = bytearray(secrets.token_bytes(32))
        raw[31] |= 128
        raw[0] |= 1
        salt = bytes(raw)
    if len(salt) != 32:
        raise ValueError("Salt must be 32 bytes")
    return format(int.from_bytes(salt, "little"), "X"), verifier(user, secret, salt)

def verify(user: str, secret: str, salt_hex: str, expected: str) -> bool:
    try:
        salt = int(salt_hex, 16).to_bytes(32, "little")
        return hmac.compare_digest(verifier(user, secret, salt).zfill(64), expected.upper().zfill(64))
    except (ValueError, TypeError, OverflowError):
        return False

def fingerprint(account: dict, key: str) -> str:
    text = f"{account['id']}:{account['s']}:{account['v']}".encode()
    return hmac.new(key.encode(), text, hashlib.sha256).hexdigest()
