# Frontage — daily runner

Runs Frontage's own Colab notebooks every weekday on GitHub's servers, in this order:

1. **Search** — only when ready leads run low; takes the next town from `config/towns.txt`.
2. **Pipeline** — only when a town file is waiting.
3. **Sender** — inside the sending window (weekdays, 08:00–17:00 Irish time).

The notebooks themselves, the business data, the reports and the logs live on the owner's
private Google Drive and are downloaded at run time. This project holds only the runner.
Passwords and keys are GitHub Secrets.

Copyright © 2026 Anzhel Dimitrov. All rights reserved. No permission is granted to copy,
modify or reuse this code.
