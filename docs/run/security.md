# Securing a deployment

At the end of this guide you will have a master key generated for the
credentials vinga stores encrypted, escrowed apart from the database
and its backups, and a way to rotate it.

## The master key

**The master key is generated once and escrowed.** Set
`VINGA_MASTER_KEY` wherever the deployment keeps its environment
secrets, alongside `VINGA_AUTH_SECRET`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

It is only needed once a credential is stored encrypted; a deployment
whose keys are all environment references never needs one. Once
ciphertext exists, losing the key means losing those credentials: the
server refuses to start with a stored secret it cannot open, naming the
entity and the slot. That refusal takes the API with it, so the way back
is the rebuild under
[Recovering a deployment that will not start](recovering-a-deployment.md):
boot on an empty database, import a kept export, enter the credentials
again and apply, which leaves no unopenable envelope behind. The key
the credentials are then entered under need not be the lost one; what
the next boot needs is a key list that opens every envelope stored, and
after a rebuild every one of them was written under the key in use.

**Rotation adds a key, and no command retires one.**
`VINGA_MASTER_KEY` holds a comma-separated list, newest first;
encryption always uses the newest and decryption tries them in order. A
new key therefore only affects secrets written after it, so every old
key must stay in the list for as long as any token written under it
remains in the database. Re-running `config <kind> secret set` for
each stored secret rewrites it under the newest key, which is how an
old key stops being needed: no command re-encrypts the stored secrets
for you.
