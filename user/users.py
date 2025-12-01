# users.py
import json
from pathlib import Path
from passlib.context import CryptContext

PWD_CTX = CryptContext(schemes=["bcrypt"], deprecated="auto")
USERS_FILE = Path("users.json")

# Пример структуры (если файла нет, можно создать вручную или через create_user)
# {
#   "admin_ivan": {"password_hash": "...", "role": "admin"},
#   "technic_petr": {"password_hash": "...", "role": "technic"}
# }

def load_users() -> dict:
    if not USERS_FILE.exists():
        return {}
    return json.loads(USERS_FILE.read_text(encoding="utf-8"))

def save_users(users: dict):
    USERS_FILE.write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")

def hash_password(password: str) -> str:
    return PWD_CTX.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return PWD_CTX.verify(password, password_hash)

def create_user(username: str, password: str, role: str = "user"):
    users = load_users()
    if username in users:
        return False, "User exists"
    users[username] = {"password_hash": hash_password(password), "role": role}
    save_users(users)
    return True, "Created"

def verify_user(username: str, password: str):
    users = load_users()
    entry = users.get(username)
    if not entry:
        return False, None
    ok = verify_password(password, entry["password_hash"])
    return ok, entry["role"] if ok else None

if __name__ == "__main__":
    username = input("Enter username: ").strip()
    if not username:
        print("Username cannot be empty.")
        exit(1)

    password = input("Enter password: ").strip()
    if not password:
        print("Password cannot be empty.")
        exit(1)

    role = input("Enter role (admin / technic / contabil): ").strip().lower()
    if not role:
        print("User type")
        exit(1)

    ok, msg = create_user(username, password, role)

    print(f"\nResult: {msg}")
    if ok:
        print(f"User '{username}' created with role '{role}'")
    else:
        print("Failed to create user.")
