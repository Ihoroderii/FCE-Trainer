Tracked runtime snapshot for moving the app to another computer.

What belongs here:
- `fce_trainer.db`
- generated listening audio copied from `static/listening/`
- generated transcripts copied from `static/transcripts/`

What does not belong here:
- `.env`
- API keys
- SMTP passwords

Refresh this snapshot before committing:

```bash
python3 scripts/sync_portable_state.py
```

On another machine you can restore it manually with:

```bash
python3 scripts/restore_portable_state.py
```

The app also restores missing runtime state from this folder automatically on startup.
