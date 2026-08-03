# Runtime secrets

Run `sudo bash scripts/provision-secrets.sh /opt/ripley-api` on the deployment
host. It prompts on the server terminal and creates:

- `ripley_api_key.txt`
- `ripley_username.txt`
- `ripley_password.txt`

The files are owned by container UID `10001` and use mode `400`. Credentials
must never be copied into chat, Compose, logs, or the repository.
