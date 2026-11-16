"""Start the web app:  python run.py   ->  http://127.0.0.1:5000"""
import os

from app import create_app
from app.seed import ADMIN_PASSWORD, DEMO_PASSWORD

app = create_app()

if __name__ == "__main__":
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", 5000))
    print(f"""
  Smart Wallet is running  ->  http://{host}:{port}

  Demo logins (created on first run)
     user : aarav@wallet.test   password: {DEMO_PASSWORD}
     admin: admin@wallet.test   password: {ADMIN_PASSWORD}

  OTPs are 'sent' to this console (and shown in the browser while DEMO_MODE=true).
""")
    app.run(host=host, port=port, threaded=True, debug=False)
