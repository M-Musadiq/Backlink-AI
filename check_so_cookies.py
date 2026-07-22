import sys, json, os
sys.path.insert(0, '.')
from cryptography.fernet import Fernet
from src.infrastructure.database import SessionLocal
from src.infrastructure.repositories.session_vault_repo import SessionVaultRepository
db = SessionLocal()
repo = SessionVaultRepository(db)
session = repo.get_by_domain('stackoverflow.com')
key = os.environ.get('VAULT_ENCRYPTION_KEY', '')
fernet = Fernet(key.encode())
decrypted = fernet.decrypt(session.session_data_encrypted.encode()).decode()
payload = json.loads(decrypted)
cookies = payload.get('cookies', [])
print(f'Total cookies: {len(cookies)}')
domains = set(c.get('domain', '') for c in cookies)
print(f'Cookie domains: {domains}')
for c in cookies[:20]:
    print(f"  {c['name']}: domain={c.get('domain','')}, path={c.get('path','')}, httpOnly={c.get('httpOnly','')}, secure={c.get('secure','')}, sameSite={c.get('sameSite','')}")
db.close()
