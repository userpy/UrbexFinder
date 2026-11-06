import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from urbex.application.users import Auth as UserService, public_user

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))


class Passwords:
    def hash(self, password):
        return hasher.hash(password)

    def verify(self, encoded, password):
        try:
            hasher.verify(encoded or DUMMY_HASH, password)
            return True
        except (VerifyMismatchError, InvalidHashError):
            return False


class Auth(UserService):
    def __init__(self, repo, config):
        super().__init__(repo, config, Passwords())
