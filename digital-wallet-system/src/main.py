"""
main.py
-------
Command-line interface for the Digital Wallet and Payment Transaction
Management System. This is the entry point for demoing the project
to your teacher/evaluator.

Run: python main.py
"""

from db import init_db
import auth
import wallet
import transaction


def print_header():
    print("=" * 60)
    print(" DIGITAL WALLET AND PAYMENT TRANSACTION MANAGEMENT SYSTEM")
    print(" (OS + DBMS Mini Project)")
    print("=" * 60)


def register_flow():
    print("\n-- Register --")
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    full_name = input("Full Name: ").strip()
    email = input("Email: ").strip()
    auth.register_user(username, password, full_name, email)


def login_flow():
    print("\n-- Login --")
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    user = auth.login_user(username, password)
    if user:
        user_session_menu(user)


def user_session_menu(user):
    w = wallet.get_wallet_by_user_id(user["user_id"])
    wallet_id = w["wallet_id"]

    while True:
        print(f"\nLogged in as {user['full_name']} | Wallet ID: {wallet_id}"
              f" | Balance: {wallet.get_balance(wallet_id):.2f}")
        print("1. Deposit")
        print("2. Withdraw")
        print("3. Transfer to another wallet")
        print("4. View transaction history")
        print("5. Logout")
        choice = input("Choose an option: ").strip()

        try:
            if choice == "1":
                amt = float(input("Amount to deposit: "))
                transaction.deposit(wallet_id, amt)
            elif choice == "2":
                amt = float(input("Amount to withdraw: "))
                transaction.withdraw(wallet_id, amt)
            elif choice == "3":
                to_wallet = int(input("Destination wallet ID: "))
                amt = float(input("Amount to transfer: "))
                transaction.transfer(wallet_id, to_wallet, amt)
            elif choice == "4":
                history = transaction.get_transaction_history(wallet_id)
                if not history:
                    print("No transactions yet.")
                for h in history:
                    print(f"  [{h['timestamp']}] {h['txn_type']:<12} "
                          f"amount={h['amount']:<10} status={h['status']}")
            elif choice == "5":
                print("Logged out.\n")
                break
            else:
                print("Invalid option.")
        except Exception as e:
            print(f"Error: {e}")


def main():
    init_db()
    print_header()
    while True:
        print("\n1. Register")
        print("2. Login")
        print("3. Exit")
        choice = input("Choose an option: ").strip()

        if choice == "1":
            register_flow()
        elif choice == "2":
            login_flow()
        elif choice == "3":
            print("Goodbye!")
            break
        else:
            print("Invalid option.")


if __name__ == "__main__":
    main()
