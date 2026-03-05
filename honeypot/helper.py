import secrets
import string

def generate_fake_git_pat():
    """GitHub PAT: prefix + 36 alphanum [web:37][web:38]"""
    prefixes = ["ghp_", "ghu_", "gho_", "ghs_", "ghr_"]
    prefix = secrets.choice(prefixes)
    return prefix + "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(36))

def generate_fake_git_basic():
    """Git username (8 chars) + password (12 chars) [web:39][web:43]"""
    user = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
    passwd = ''.join(secrets.choice(string.ascii_letters + string.digits + "!@#$%^&*") for _ in range(12))
    return user, passwd

def generate_fake_db_password(length=20):
    """Generic DB password: 20 chars with symbols [web:40][web:44]"""
    chars = string.ascii_letters + string.digits + "!@#$%^&*()_+-="
    return ''.join(secrets.choice(chars) for _ in range(length))

def generate_fake_git_db_creds():
    pat = generate_fake_git_pat()
    user, passwd = generate_fake_git_basic()
    db_pass = generate_fake_db_password()
    return pat, user, passwd, db_pass

# Example usage
if __name__ == "__main__":
    pat, user, passwd, db_pass = generate_fake_git_db_creds()
    print("GITHUB_TOKEN=", pat)
    print("GIT_USER=", user)
    print("GIT_PASS=", passwd)
    print("DB_PASSWORD=", db_pass)
