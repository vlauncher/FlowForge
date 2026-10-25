# Dependency & Infrastructure Notes

## PostgreSQL Container Image
- **Image Tag:** `postgres:16-alpine` (Image ID: `deb28ee47118`)
- **Reason:** Current production-grade PostgreSQL release, lightweight Alpine base (117MB), pre-cached locally on the host.
- **Port:** `127.0.0.1:5432:5432`
- **Default Database:** `flowforge`
- **Default User:** `flowforge`
- **Healthcheck Probe:** `pg_isready -U flowforge -d flowforge`

## Python & Runtime
- **Runtime:** Python 3.14.4
- **ORM / Driver:** SQLAlchemy 2.0 async + `asyncpg` 0.32.0
- **Migration Engine:** Alembic 1.20.1
- **Password Hashing:** Argon2id via `argon2-cffi` 25.1.0
- **Token Encoding:** PyJWT 2.15.1 with HS256
