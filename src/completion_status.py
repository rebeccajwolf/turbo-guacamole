import json
from pathlib import Path
from datetime import datetime

class CompletionStatus:
    def __init__(self):
        self.status_file = Path(__file__).resolve().parent.parent / "logs" / "completion_status.json"
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        self.status = self._load_status()

    def _load_status(self):
        try:
            if self.status_file.exists():
                with open(self.status_file, 'r') as f:
                    return json.load(f)
            return {}
        except Exception:
            return {}

    def _save_status(self):
        with open(self.status_file, 'w') as f:
            json.dump(self.status, f, indent=4)

    def get_account_status(self, account_email):
        today = datetime.now().strftime("%Y-%m-%d")
        if account_email not in self.status:
            self.status[account_email] = {}
        
        # If the date is different from today, reset the status
        if today not in self.status[account_email]:
            self.status[account_email][today] = {
                # "login": False,
                # "daily_set": False,
                "punch_cards": False,
                "promotions": False,
                "desktop_searches": False,
                "mobile_searches": False
            }
            # Clear any old dates for this account
            for date in list(self.status[account_email].keys()):
                if date != today:
                    del self.status[account_email][date]
            self._save_status()
            
        return self.status[account_email][today]

    def mark_completed(self, account_email, task):
        today = datetime.now().strftime("%Y-%m-%d")
        if account_email not in self.status:
            self.status[account_email] = {}
        if today not in self.status[account_email]:
            self.status[account_email][today] = {}
        self.status[account_email][today][task] = True
        self._save_status()

    def is_completed(self, account_email, task):
        status = self.get_account_status(account_email)
        return status.get(task, False)

    def clear_old_status(self):
        """Clear status entries older than 7 days"""
        today = datetime.now().strftime("%Y-%m-%d")
        for account in list(self.status.keys()):
            for date in list(self.status[account].keys()):
                if date != today:
                    del self.status[account][date]
            if not self.status[account]:
                del self.status[account]
        self._save_status() 